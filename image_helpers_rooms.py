# image_helpers_rooms.py
from __future__ import annotations

import os, time
from datetime import datetime as dt
from typing import Dict, List, Tuple, Optional
import logging

# Reuse the proven photo pipeline (resize + watermark + JPEG save + limits)
from image_helpers import (
    process_image, save_jpeg, read_limited,  # core I/O + processing
    ALLOWED_MIMES, FILE_SIZE_LIMIT_BYTES,    # limits & validation
)

from PIL import Image

# ------------ Logging ------------
logger = logging.getLogger("student_palace.room_uploads")

# ------------ Config (rooms) ------------
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")
ROOM_UPLOAD_DIR_ABS = os.path.join(STATIC_ROOT, "uploads", "rooms")   # /static/uploads/rooms
ROOM_UPLOAD_DIR_REL = "uploads/rooms"                                 # stored in DB (no leading slash)

MAX_FILES_PER_ROOM = 5

# ------------ FS helpers ------------

def ensure_room_upload_dir() -> None:
    os.makedirs(ROOM_UPLOAD_DIR_ABS, exist_ok=True)

def static_rel_path_room(filename: str) -> str:
    # store WITHOUT a leading slash; render with url_for('static', filename=...)
    return f"{ROOM_UPLOAD_DIR_REL}/{filename}"

def file_abs_path_room(filename: str) -> str:
    return os.path.join(ROOM_UPLOAD_DIR_ABS, filename)

# ------------ DB schema (add-only safe) ------------

def assert_room_images_schema(conn) -> None:
    """
    Ensures table `room_images` exists with all required columns.
    Add-only; safe to call before insert/select.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS room_images (
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
    # Add-only guards in case an older table exists
    def _safe_add(sql_col: str):
        try:
            conn.execute(f"ALTER TABLE room_images ADD COLUMN {sql_col}")
        except Exception:
            pass

    _safe_add("room_id INTEGER NOT NULL")
    _safe_add("file_name TEXT NOT NULL DEFAULT ''")
    _safe_add("filename TEXT NOT NULL DEFAULT ''")
    _safe_add("file_path TEXT NOT NULL DEFAULT ''")
    _safe_add("width INTEGER NOT NULL DEFAULT 0")
    _safe_add("height INTEGER NOT NULL DEFAULT 0")
    _safe_add("bytes INTEGER NOT NULL DEFAULT 0")
    _safe_add("is_primary INTEGER NOT NULL DEFAULT 0")
    _safe_add("sort_order INTEGER NOT NULL DEFAULT 0")
    _safe_add("created_at TEXT NOT NULL DEFAULT ''")

# ------------ DB ops (rooms) ------------

def _count_for_room(conn, rid: int) -> int:
    r = conn.execute("SELECT COUNT(*) AS c FROM room_images WHERE room_id=?", (rid,)).fetchone()
    return int(r["c"] if r and "c" in r.keys() else 0)

def _next_sort_order(conn, rid: int) -> int:
    r = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS mx FROM room_images WHERE room_id=?", (rid,)).fetchone()
    mx = int(r["mx"] if r and "mx" in r.keys() and r["mx"] is not None else 0)
    return mx + 1

def _ensure_primary_flag(conn, rid: int) -> int:
    r = conn.execute(
        "SELECT COUNT(*) AS c FROM room_images WHERE room_id=? AND is_primary=1", (rid,)
    ).fetchone()
    c = int(r["c"] if r and "c" in r.keys() else 0)
    return 1 if c == 0 else 0

def select_room_images(conn, rid: int) -> List[Dict]:
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
        "file_path": r["file_path"],   # relative path under /static
        "filename": r["filename"],
        "width": int(r["width"]),
        "height": int(r["height"]),
        "bytes": int(r["bytes"]),
        "sort_order": int(r["sort_order"]),
        "created_at": r["created_at"],
    } for r in rows]

def set_room_primary(conn, rid: int, img_id: int) -> None:
    conn.execute("UPDATE room_images SET is_primary=0 WHERE room_id=?", (rid,))
    conn.execute("UPDATE room_images SET is_primary=1 WHERE id=? AND room_id=?", (img_id, rid))

def delete_room_image(conn, rid: int, img_id: int) -> Optional[str]:
    """
    Delete row and return filename (so caller can remove file from disk),
    or None if not found.
    """
    row = conn.execute("""
        SELECT id, COALESCE(filename, file_name) AS filename
          FROM room_images
         WHERE id=? AND room_id=?
    """, (img_id, rid)).fetchone()
    if not row:
        return None
    fname = row["filename"]
    conn.execute("DELETE FROM room_images WHERE id=? AND room_id=?", (img_id, rid))
    # If we deleted the primary, pick the first remaining as new primary
    nxt = conn.execute("""
        SELECT id FROM room_images
         WHERE room_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (rid,)).fetchone()
    if nxt:
        conn.execute("UPDATE room_images SET is_primary=1 WHERE id=?", (nxt["id"],))
    return fname

# ------------ Upload flow (rooms) ------------

def accept_room_upload(conn, rid: int, file_storage, *, enforce_limit: bool = True) -> Tuple[bool, str]:
    """
    Returns (ok, message). Saves to disk + DB or reports a reason.
    Mirrors house accept_upload(), but scoped to a room.
    """
    if not file_storage:
        return False, "No file."

    original_name = getattr(file_storage, "filename", "") or "unnamed"
    mimetype = (getattr(file_storage, "mimetype", None) or "").lower()

    if enforce_limit and _count_for_room(conn, rid) >= MAX_FILES_PER_ROOM:
        logger.info(f"[ROOM UPLOAD] room={rid} name={original_name!r} mime={mimetype} skipped=limit")
        return False, f"Room already has {MAX_FILES_PER_ROOM} photos."

    if mimetype not in ALLOWED_MIMES:
        logger.info(f"[ROOM UPLOAD] room={rid} name={original_name!r} mime={mimetype} skipped=bad_mime")
        return False, "Unsupported image type."

    buf = read_limited(file_storage)
    if not buf:
        logger.info(f"[ROOM UPLOAD] room={rid} name={original_name!r} skipped=empty_read")
        return False, "Could not read the file."
    if len(buf) > FILE_SIZE_LIMIT_BYTES:
        logger.info(f"[ROOM UPLOAD] room={rid} name={original_name!r} skipped=too_large size={len(buf)}")
        return False, "File is larger than 5 MB."

    # Process (open → resize → watermark)
    try:
        im = process_image(buf)
    except Exception:
        logger.exception(f"[ROOM UPLOAD] room={rid} name={original_name!r} failed=invalid_image")
        return False, "File is not a valid image."

    # Write to disk
    ensure_room_upload_dir()
    ts = dt.utcnow().strftime("%Y%m%d%H%M%S")
    import secrets
    token = secrets.token_hex(4)
    fname = f"room{rid}_{ts}_{token}.jpg"
    abs_path = file_abs_path_room(fname)

    try:
        w, h, byt = save_jpeg(im, abs_path)
    except Exception:
        logger.exception(f"[ROOM UPLOAD] room={rid} name={original_name!r} failed=fs_write")
        return False, "Server storage is not available."

    # Insert DB row
    try:
        assert_room_images_schema(conn)
        file_path = static_rel_path_room(fname)
        conn.execute("""
            INSERT INTO room_images(
              room_id, file_name, filename, file_path, width, height, bytes,
              is_primary, sort_order, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            rid, fname, fname, file_path, w, h, byt,
            _ensure_primary_flag(conn, rid), _next_sort_order(conn, rid),
            dt.utcnow().isoformat()
        ))
    except Exception as e:
        # Roll back disk save if DB insert fails
        try:
            os.remove(abs_path)
        except Exception:
            pass
        logger.exception(f"[ROOM UPLOAD] room={rid} name={original_name!r} failed=db_insert")
        return False, f"Couldn’t record image in DB: {e}"

    logger.info(
        f"[ROOM UPLOAD] room={rid} name={original_name!r} saved={fname!r} "
        f"mime={mimetype} size_bytes={byt} dims={w}x{h}"
    )
    return True, "Uploaded"
