# image_helpers_rooms.py
from __future__ import annotations
import os
from datetime import datetime as dt
from image_helpers import (
    _ensure_dir, _uuid_jpg, _open_pil_safely, _resize_longest,
    _save_jpeg_85, _watermark_text, _ext_ok, _file_size_ok,
    MAX_BYTES, ALLOWED_EXTS, file_abs_path as _file_abs_path_base,
)

# Folder & limits specific to ROOM photos
UPLOADS_SUBDIR = "uploads/rooms"
DISK_DIR = os.path.join("static", UPLOADS_SUBDIR)
MAX_FILES_PER_ROOM = 5

def file_abs_path_room(fname: str) -> str:
    return _file_abs_path_base(fname, base_dir=DISK_DIR)

def assert_room_images_schema(conn):
    # Mirror of house_images but for rooms
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
    conn.commit()

def select_room_images(conn, rid: int):
    return conn.execute("""
        SELECT id,
               COALESCE(filename, file_name) AS filename,
               file_path, width, height, bytes, is_primary, sort_order, created_at
          FROM room_images
         WHERE room_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (rid,)).fetchall()

def _next_sort_order(conn, rid: int) -> int:
    r = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS m FROM room_images WHERE room_id=?", (rid,)).fetchone()
    return int(r["m"] or 0) + 10

def _current_count(conn, rid: int) -> int:
    r = conn.execute("SELECT COUNT(*) AS c FROM room_images WHERE room_id=?", (rid,)).fetchone()
    return int(r["c"] or 0)

def accept_upload_room(conn, rid: int, werk_file, enforce_limit=True):
    # Basic guards
    fname_src = getattr(werk_file, "filename", "") or ""
    if not fname_src.strip():
        return False, "No file name."
    if not _ext_ok(fname_src, ALLOWED_EXTS):
        return False, f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTS)}"
    if not _file_size_ok(werk_file, MAX_BYTES):
        return False, "File too large (max 5 MB)."
    if enforce_limit and _current_count(conn, rid) >= MAX_FILES_PER_ROOM:
        return False, f"Room already has {MAX_FILES_PER_ROOM} photos."

    _ensure_dir(DISK_DIR)

    # Process with the proven house pipeline
    try:
        im = _open_pil_safely(werk_file)
        im = _resize_longest(im, 1600)
        im = _watermark_text(im, "Student Palace")
    except Exception as e:
        return False, f"Could not process image: {e}"

    # Save to disk
    out_name = _uuid_jpg()
    out_rel = f"{UPLOADS_SUBDIR}/{out_name}"
    out_abs = os.path.join("static", out_rel)
    try:
        _save_jpeg_85(im, out_abs)
    except Exception as e:
        return False, f"Could not save file: {e}"

    # Insert DB row
    try:
        width, height = im.size
        bytes_size = os.path.getsize(out_abs)
        sort_order = _next_sort_order(conn, rid)
        is_first = (_current_count(conn, rid) == 0)
        is_primary = 1 if is_first else 0

        conn.execute("""
            INSERT INTO room_images
                (room_id, file_name, filename, file_path, width, height, bytes,
                 is_primary, sort_order, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            rid, out_name, out_name, out_rel,
            int(width), int(height), int(bytes_size),
            int(is_primary), int(sort_order), dt.utcnow().isoformat()
        ))
        return True, "OK"
    except Exception as e:
        try: os.remove(out_abs)
        except Exception: pass
        return False, f"DB insert failed: {e}"

def set_primary_room(conn, rid: int, img_id: int):
    conn.execute("UPDATE room_images SET is_primary=0 WHERE room_id=?", (rid,))
    conn.execute("UPDATE room_images SET is_primary=1 WHERE id=? AND room_id=?", (img_id, rid,))

def delete_room_image(conn, rid: int, img_id: int):
    r = conn.execute("""
        SELECT COALESCE(filename, file_name) AS fname
          FROM room_images WHERE id=? AND room_id=?
    """, (img_id, rid)).fetchone()
    if not r:
        return None
    fname = r["fname"]
    conn.execute("DELETE FROM room_images WHERE id=? AND room_id=?", (img_id, rid))
    return fname
