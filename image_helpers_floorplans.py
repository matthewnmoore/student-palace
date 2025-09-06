# image_helpers_floorplans.py
from __future__ import annotations

import os, io, uuid, datetime, logging
from typing import Tuple, Optional

from PIL import Image

# Reuse the shared house-photo pipeline (identical look & behavior)
from image_helpers import (
    logger,                    # "student_palace.uploads"
    read_limited,              # size-limited reader with stream reset
    FILE_SIZE_LIMIT_BYTES,     # 5 MB
    ALLOWED_MIMES,             # {"image/jpeg","image/png","image/webp","image/gif"}
    process_image,             # open → EXIF fix → resize(1600) → portrait letterbox (light pink) → watermark (top-left; +2ch on landscape)
)

# === Config ===
MAX_FILES_PER_HOUSE_PLANS = 5
# Relative under /static
FLOORPLAN_UPLOAD_DIR = "uploads/floorplans"

def _ensure_upload_dir_abs() -> str:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
    target = os.path.join(base, FLOORPLAN_UPLOAD_DIR)
    os.makedirs(target, exist_ok=True)
    return target

def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat(timespec="seconds")

# ---------- Disk helper ----------
def file_abs_path_plan(filename_only: str) -> str:
    folder = _ensure_upload_dir_abs()
    return os.path.join(folder, filename_only)

# ---------- Image processing (reuse shared pipeline, then JPEG to bytes) ----------
def _process_plan_image(buf: bytes) -> Tuple[bytes, int, int]:
    """
    Uses the shared process_image() so floorplans match photos/rooms:
    open → EXIF fix → resize longest to 1600 → (portrait) add light-pink sidebars to reach 16:9 →
    watermark top-left (landscape is nudged ~2 chars to the right) → save optimized JPEG to bytes.
    """
    im: Image.Image = process_image(buf)  # returns PIL Image already watermarked
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=85, optimize=True, progressive=True)
    data = out.getvalue()
    w, h = im.size
    return data, w, h

# ---------- Schema (add-only) ----------
REQUIRED_COLS = {
    "id","house_id","file_name","filename","file_path",
    "width","height","bytes","is_primary","sort_order","created_at"
}

def assert_house_floorplans_schema(conn) -> None:
    """
    Ensures table `house_floorplans` exists and has all required columns.
    Safe to call before any insert/select.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS house_floorplans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL,
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
    # Add-only guards for legacy DBs
    def _safe_add(col_sql: str):
        try:
            conn.execute(f"ALTER TABLE house_floorplans ADD COLUMN {col_sql}")
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

# ---------- Queries ----------
def select_plans(conn, house_id: int):
    return conn.execute("""
        SELECT id,
               COALESCE(filename, file_name) AS filename,
               file_path, width, height, bytes,
               is_primary, sort_order, created_at
          FROM house_floorplans
         WHERE house_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (house_id,)).fetchall()

def _next_sort_order(conn, house_id: int) -> int:
    row = conn.execute("""
        SELECT MAX(sort_order) AS mx FROM house_floorplans WHERE house_id=?
    """, (house_id,)).fetchone()
    return (row["mx"] or 0) + 10

# ---------- Upload ----------
def accept_upload_plan(conn, house_id: int, werk_file, enforce_limit: bool = True) -> Tuple[bool, str]:
    """
    Accept a single uploaded floorplan image, process + write to disk, insert DB row.
    Returns (ok, message).
    """
    if not werk_file or not getattr(werk_file, "filename", "").strip():
        return False, "No file."

    mimetype = (getattr(werk_file, "mimetype", None) or "").lower()
    if mimetype not in ALLOWED_MIMES:
        return False, "Unsupported image type."

    if enforce_limit:
        existing = len(select_plans(conn, house_id))
        if existing >= MAX_FILES_PER_HOUSE_PLANS:
            return False, f"House already has {MAX_FILES_PER_HOUSE_PLANS} floor plans."

    data_in = read_limited(werk_file)
    if not data_in:
        return False, "Could not read the file."
    if len(data_in) > FILE_SIZE_LIMIT_BYTES:
        return False, "File is larger than 5 MB."

    try:
        jpeg_bytes, w, h = _process_plan_image(data_in)
    except Exception:
        logger.exception(f"[UPLOAD-FP] house={house_id} failed=process")
        return False, "Could not process image."

    _ensure_upload_dir_abs()
    name = f"{uuid.uuid4().hex}.jpg"
    abs_path = file_abs_path_plan(name)
    try:
        with open(abs_path, "wb") as f:
            f.write(jpeg_bytes)
        size_bytes = len(jpeg_bytes)
    except Exception:
        logger.exception(f"[UPLOAD-FP] house={house_id} failed=fs_write")
        return False, "Server storage is not available."

    # Insert row
    try:
        assert_house_floorplans_schema(conn)
        rel_path = f"{FLOORPLAN_UPLOAD_DIR}/{name}"
        first_for_house = (len(select_plans(conn, house_id)) == 0)
        conn.execute("""
            INSERT INTO house_floorplans
            (house_id, file_name, filename, file_path, width, height, bytes,
             is_primary, sort_order, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            house_id, name, name, rel_path, w, h, size_bytes,
            1 if first_for_house else 0, _next_sort_order(conn, house_id), _now_iso()
        ))
    except Exception as e:
        # cleanup file on DB error
        try:
            os.remove(abs_path)
        except Exception:
            pass
        logger.exception(f"[UPLOAD-FP] house={house_id} failed=db_insert")
        return False, f"Couldn’t record image in DB: {e}"

    logger.info(f"[UPLOAD-FP] house={house_id} saved={name!r} size_bytes={size_bytes} dims={w}x{h}")
    return True, "OK"

# ---------- Primary & Delete ----------
def set_primary_plan(conn, house_id: int, plan_id: int) -> None:
    conn.execute("UPDATE house_floorplans SET is_primary=0 WHERE house_id=?", (house_id,))
    conn.execute("UPDATE house_floorplans SET is_primary=1 WHERE id=? AND house_id=?", (plan_id, house_id,))

def delete_plan(conn, house_id: int, plan_id: int) -> Optional[str]:
    row = conn.execute("""
        SELECT id, COALESCE(filename, file_name) AS filename
          FROM house_floorplans
         WHERE id=? AND house_id=?
    """, (plan_id, house_id)).fetchone()
    if not row:
        return None
    fname = row["filename"]
    conn.execute("DELETE FROM house_floorplans WHERE id=?", (plan_id,))
    # re-pick a primary if needed
    row2 = conn.execute("""
        SELECT id FROM house_floorplans
         WHERE house_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (house_id,)).fetchone()
    if row2:
        conn.execute("UPDATE house_floorplans SET is_primary=1 WHERE id=?", (row2["id"],))
    return fname
