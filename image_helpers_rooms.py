# image_helpers_rooms.py
from __future__ import annotations

import os
from datetime import datetime as dt
from typing import Dict, List, Tuple, Optional

# Reuse the shared house-photo pipeline (now includes purple padding + top-left watermark)
from image_helpers import (
    logger,                # same logger
    process_image,         # open → EXIF fix → resize(1600) → pad 16:9 (brand light) → watermark (top-left)
    save_jpeg,             # save as optimized JPEG
    read_limited,          # size-limited reader (seeks back)
    FILE_SIZE_LIMIT_BYTES, # 5 MB
    ALLOWED_MIMES,         # {"image/jpeg","image/png","image/webp","image/gif"}
)

# ------------ Config (rooms) ------------
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
STATIC_ROOT   = os.path.join(PROJECT_ROOT, "static")
ROOMS_UPLOAD_DIR_ABS = os.path.join(STATIC_ROOT, "uploads", "rooms")  # /static/uploads/rooms
MAX_FILES_PER_ROOM = 5

def ensure_upload_dir_room() -> None:
    os.makedirs(ROOMS_UPLOAD_DIR_ABS, exist_ok=True)

def static_rel_path_room(filename: str) -> str:
    # store WITHOUT leading slash; render with url_for('static', filename=...)
    return f"uploads/rooms/{filename}"

def file_abs_path_room(filename: str) -> str:
    return os.path.join(ROOMS_UPLOAD_DIR_ABS, filename)

# ------------ Schema guard (rooms) ------------

REQUIRED_COLS_ROOM = {
    "id","room_id","file_name","filename","file_path",
    "width","height","bytes","is_primary","sort_order","created_at"
}

def _cols(conn, table: str) -> List[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

def assert_room_images_schema(conn) -> None:
    # Create if missing (covers modern schema)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS room_images(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            bytes INTEGER NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            filename TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Add-only guards for very old deployments (no-op if columns already exist)
    def _safe_add(col_sql: str):
        try:
            conn.execute(f"ALTER TABLE room_images ADD COLUMN {col_sql}")
        except Exception:
            pass
    _safe_add("file_name TEXT NOT NULL DEFAULT ''")
    _safe_add("filename TEXT NOT NULL DEFAULT ''")
    _safe_add("file_path TEXT NOT NULL DEFAULT ''")
    _safe_add("width INTEGER NOT NULL DEFAULT 0")
    _safe_add("height INTEGER NOT NULL DEFAULT 0")
    _safe_add("bytes INTEGER NOT NULL DEFAULT 0")
    _safe_add("is_primary INTEGER NOT NULL DEFAULT 0")
    _safe_add("sort_order INTEGER NOT NULL DEFAULT 0")
    _safe_add("created_at TEXT NOT NULL DEFAULT ''")

    # Verify required set
    cols = set(_cols(conn, "room_images"))
    missing = REQUIRED_COLS_ROOM - cols
    if missing:
        raise RuntimeError(f"room_images schema missing columns: {sorted(missing)}")

# ------------ DB ops (rooms) ------------

def _count_for_room(conn, rid: int) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) AS c FROM room_images WHERE room_id=?", (rid,)
    ).fetchone()["c"])

def _next_sort_order_room(conn, rid: int) -> int:
    r = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS mx FROM room_images WHERE room_id=?",
        (rid,)
    ).fetchone()
    return (int(r["mx"]) if r else 0) + 1

def _ensure_primary_flag_room(conn, rid: int) -> int:
    r = conn.execute(
        "SELECT COUNT(*) AS c FROM room_images WHERE room_id=? AND is_primary=1",
        (rid,)
    ).fetchone()
    return 1 if (r and int(r["c"]) == 0) else 0

def _insert_image_row_room(conn, rid: int, fname: str, width: int, height: int, bytes_: int) -> None:
    file_path = static_rel_path_room(fname)
    values = (
        rid, fname, fname, file_path, width, height, bytes_,
        _ensure_primary_flag_room(conn, rid), _next_sort_order_room(conn, rid),
        dt.utcnow().isoformat()
    )
    conn.execute("""
        INSERT INTO room_images(
          room_id, file_name, filename, file_path, width, height, bytes,
          is_primary, sort_order, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
    """, values)

def select_images_room(conn, rid: int) -> List[Dict]:
    rows = conn.execute("""
        SELECT id,
               COALESCE(filename, file_name) AS filename,
               file_path, width, height, bytes,
               is_primary, sort_order, created_at
          FROM room_images
         WHERE room_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (rid,)).fetchall()
    return [{
        "id": r["id"],
        "is_primary": int(r["is_primary"]) == 1,
        "file_path": r["file_path"],
        "filename": r["filename"],
        "width": int(r["width"]),
        "height": int(r["height"]),
        "bytes": int(r["bytes"]),
        "sort_order": int(r["sort_order"]),
        "created_at": r["created_at"],
    } for r in rows]

def set_primary_room(conn, rid: int, img_id: int) -> None:
    conn.execute("UPDATE room_images SET is_primary=0 WHERE room_id=?", (rid,))
    conn.execute("UPDATE room_images SET is_primary=1 WHERE id=? AND room_id=?", (img_id, rid))

def delete_image_room(conn, rid: int, img_id: int) -> Optional[str]:
    """
    Delete one room image and, if it was the primary, promote the next best image
    (by sort_order, then id) to be the new primary.
    Returns the filename so the caller can delete the file from disk, or None if not found.
    """
    row = conn.execute("""
        SELECT id,
               COALESCE(filename, file_name) AS filename,
               COALESCE(is_primary, 0)       AS is_primary
          FROM room_images
         WHERE id=? AND room_id=?
    """, (img_id, rid)).fetchone()

    if not row:
        return None

    fname = row["filename"]
    was_primary = int(row["is_primary"]) == 1

    # Remove the row
    conn.execute("DELETE FROM room_images WHERE id=? AND room_id=?", (img_id, rid))

    # If we deleted the primary, pick a new one if any remain
    if was_primary:
        next_row = conn.execute("""
            SELECT id
              FROM room_images
             WHERE room_id=?
             ORDER BY sort_order ASC, id ASC
             LIMIT 1
        """, (rid,)).fetchone()

        if next_row:
            conn.execute("UPDATE room_images SET is_primary=0 WHERE room_id=?", (rid,))
            conn.execute("UPDATE room_images SET is_primary=1 WHERE id=? AND room_id=?", (next_row["id"], rid))

    return fname

# ------------ Upload (rooms) ------------

def accept_upload_room(conn, rid: int, file_storage, *, enforce_limit: bool = True) -> Tuple[bool, str]:
    """
    Returns (ok, message). Reads the file, runs the shared processing pipeline,
    saves the JPEG to disk, and inserts a DB row in room_images.
    """
    original_name = getattr(file_storage, "filename", "") or "unnamed"
    mimetype = (getattr(file_storage, "mimetype", None) or "").lower()

    if enforce_limit and _count_for_room(conn, rid) >= MAX_FILES_PER_ROOM:
        logger.info(f"[UPLOAD-RM] room={rid} name={original_name!r} mime={mimetype} skipped=limit_reached")
        return False, f"Room already has {MAX_FILES_PER_ROOM} photos."

    if mimetype not in ALLOWED_MIMES:
        logger.info(f"[UPLOAD-RM] room={rid} name={original_name!r} mime={mimetype} skipped=bad_mime")
        return False, "Unsupported image type."

    data = read_limited(file_storage)
    if not data:
        logger.info(f"[UPLOAD-RM] room={rid} name={original_name!r} skipped=empty_read")
        return False, "Could not read the file."
    if len(data) > FILE_SIZE_LIMIT_BYTES:
        logger.info(f"[UPLOAD-RM] room={rid} name={original_name!r} skipped=too_large size={len(data)}")
        return False, "File is larger than 5 MB."

    try:
        im = process_image(data)  # shared pipeline
    except Exception:
        logger.exception(f"[UPLOAD-RM] room={rid} name={original_name!r} failed=invalid_image")
        return False, "File is not a valid image."

    ensure_upload_dir_room()
    ts = dt.utcnow().strftime("%Y%m%d%H%M%S")

    # include rid in filename to avoid collisions & for easier ops
    from secrets import token_hex
    fname = f"room{rid}_{ts}_{token_hex(4)}.jpg"
    abs_path = file_abs_path_room(fname)

    try:
        w, h, byt = save_jpeg(im, abs_path)
    except Exception:
        logger.exception(f"[UPLOAD-RM] room={rid} name={original_name!r} failed=fs_write")
        return False, "Server storage is not available."

    try:
        assert_room_images_schema(conn)
        _insert_image_row_room(conn, rid, fname, w, h, byt)
    except Exception as e:
        try:
            os.remove(abs_path)
        except Exception:
            pass
        logger.exception(f"[UPLOAD-RM] room={rid} name={original_name!r} failed=db_insert")
        return False, f"Couldn’t record image in DB: {e}"

    logger.info(
        f"[UPLOAD-RM] room={rid} name={original_name!r} saved={fname!r} size_bytes={byt} dims={w}x{h}"
    )
    return True, "Uploaded"
