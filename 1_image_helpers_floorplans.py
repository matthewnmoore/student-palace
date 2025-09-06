# image_helpers_floorplans.py
from __future__ import annotations

import os, io, uuid, datetime
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

from db import get_db

# === Config (mirrors photos) ===
MAX_FILES_PER_HOUSE_PLANS = 5
# Relative to /static
FLOORPLAN_UPLOAD_DIR = "uploads/floorplans"

# Ensure the disk folder exists (best-effort; safe if already present)
def _ensure_upload_dir_abs() -> str:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
    target = os.path.join(base, FLOORPLAN_UPLOAD_DIR)
    os.makedirs(target, exist_ok=True)
    return target

def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat(timespec="seconds")

# -------- Schema helpers (add-only, no destructive changes) --------
def assert_house_floorplans_schema(conn) -> None:
    """
    Ensures table `house_floorplans` exists and has all required columns.
    This is add-only and safe to call before any insert/select.
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
    # Add-only guards (for parity if table was created earlier without some columns)
    def _safe_add(col_sql: str):
        try:
            conn.execute(f"ALTER TABLE house_floorplans ADD COLUMN {col_sql}")
        except Exception:
            pass

    # Keep both filename/file_name in sync just like photos
    # (Columns above already include both; these lines are just in case of legacy)
    _safe_add("file_name TEXT NOT NULL DEFAULT ''")
    _safe_add("filename TEXT NOT NULL DEFAULT ''")
    _safe_add("file_path TEXT NOT NULL DEFAULT ''")
    _safe_add("width INTEGER NOT NULL DEFAULT 0")
    _safe_add("height INTEGER NOT NULL DEFAULT 0")
    _safe_add("bytes INTEGER NOT NULL DEFAULT 0")
    _safe_add("is_primary INTEGER NOT NULL DEFAULT 0")
    _safe_add("sort_order INTEGER NOT NULL DEFAULT 0")
    _safe_add("created_at TEXT NOT NULL DEFAULT ''")

# -------- Disk helper (absolute path from stored filename) --------
def file_abs_path_plan(filename_only: str) -> str:
    """
    Given just the stored filename (e.g. 'abc123.jpg'), return absolute
    disk path under static/uploads/floorplans.
    """
    folder = _ensure_upload_dir_abs()
    return os.path.join(folder, filename_only)

# -------- Image processing (same approach as photos) --------
def _process_image(fp) -> Tuple[bytes, int, int]:
    """
    Open bytes/file, auto-rotate, convert to RGB, resize longest side to 1600,
    add 'Student Palace' watermark bottom-right, save as optimized JPEG.
    Returns (jpeg_bytes, width, height)
    """
    im = Image.open(fp)
    # Auto-orient
    try:
        im = Image.Image.transpose(im, Image.TRANSPOSE)  # no-op fallback
    except Exception:
        pass
    try:
        im = Image.open(fp)
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass

    im = im.convert("RGB")

    # Resize longest side to 1600
    MAX_SIDE = 1600
    w, h = im.size
    scale = min(1.0, MAX_SIDE / float(max(w, h)))
    if scale < 1.0:
        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # Watermark
    draw = ImageDraw.Draw(im)
    text = "Student Palace"
    W, H = im.size
    # Font size ~ width/16 with safe fallback
    fontsize = max(12, int(W / 16))
    try:
        font = ImageFont.truetype("arial.ttf", fontsize)
    except Exception:
        font = ImageFont.load_default()

    tw, th = draw.textsize(text, font=font)
    pad = max(6, fontsize // 4)
    x = W - tw - pad
    y = H - th - pad

    # Shadow + text
    shadow_offset = max(1, fontsize // 16)
    draw.text((x + shadow_offset, y + shadow_offset), text, fill=(0, 0, 0, 128), font=font)
    draw.text((x, y), text, fill=(255, 255, 255, 210), font=font)

    buf = io.BytesIO()
    im.save(buf, format="JPEG", optimize=True, progressive=True, quality=85)
    data = buf.getvalue()
    im_w, im_h = im.size
    return data, im_w, im_h

# -------- CRUD-ish helpers for floorplans --------
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

def accept_upload_plan(conn, house_id: int, werk_file, enforce_limit: bool = True) -> Tuple[bool, str]:
    """
    Accept a single uploaded file for a floor plan, process + write to disk, insert DB row.
    Returns (ok, message).
    """
    if not werk_file or not getattr(werk_file, "filename", "").strip():
        return False, "No file."

    # Validate simple content type (match Photos behavior)
    ctype = getattr(werk_file, "mimetype", "") or ""
    if not ctype.startswith("image/"):
        return False, "Not an image."

    # Enforce limit if asked
    if enforce_limit:
        existing = len(select_plans(conn, house_id))
        if existing >= MAX_FILES_PER_HOUSE_PLANS:
            return False, f"House already has {MAX_FILES_PER_HOUSE_PLANS} floor plans."

    # Read and process
    raw_bytes = werk_file.read()
    if not raw_bytes:
        return False, "Empty upload."
    try:
        data, w, h = _process_image(io.BytesIO(raw_bytes))
    except Exception as e:
        return False, f"Could not process image: {e}"

    # Generate name and write to disk
    _ensure_upload_dir_abs()
    name = f"{uuid.uuid4().hex}.jpg"
    abs_path = file_abs_path_plan(name)
    with open(abs_path, "wb") as f:
        f.write(data)
    size_bytes = len(data)

    # Insert DB
    rel_path = f"{FLOORPLAN_UPLOAD_DIR}/{name}"  # relative under /static
    first_for_house = (len(select_plans(conn, house_id)) == 0)
    sort_order = _next_sort_order(conn, house_id)
    now = _now_iso()

    conn.execute("""
        INSERT INTO house_floorplans
        (house_id, file_name, filename, file_path, width, height, bytes,
         is_primary, sort_order, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        house_id, name, name, rel_path, w, h, size_bytes,
        1 if first_for_house else 0, sort_order, now
    ))
    return True, "OK"

def set_primary_plan(conn, house_id: int, plan_id: int) -> None:
    # Clear existing, set chosen one
    conn.execute("UPDATE house_floorplans SET is_primary=0 WHERE house_id=?", (house_id,))
    conn.execute("UPDATE house_floorplans SET is_primary=1 WHERE id=? AND house_id=?", (plan_id, house_id,))

def delete_plan(conn, house_id: int, plan_id: int) -> Optional[str]:
    """
    Delete row, return filename (for caller to remove from disk), or None if not found.
    """
    row = conn.execute("""
        SELECT id, COALESCE(filename, file_name) AS filename
          FROM house_floorplans
         WHERE id=? AND house_id=?
    """, (plan_id, house_id)).fetchone()
    if not row:
        return None

    fname = row["filename"]
    conn.execute("DELETE FROM house_floorplans WHERE id=?", (plan_id,))
    # If we deleted the primary, try to set the first remaining as primary
    row2 = conn.execute("""
        SELECT id FROM house_floorplans
         WHERE house_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (house_id,)).fetchone()
    if row2:
        conn.execute("UPDATE house_floorplans SET is_primary=1 WHERE id=?", (row2["id"],))
    return fname
