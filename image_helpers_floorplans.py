# image_helpers_floorplans.py
from __future__ import annotations

import os, io, uuid, datetime, logging
from typing import List, Tuple, Optional

from PIL import Image, ImageOps, ImageDraw, ImageFont

# Reuse the proven house-photo pipeline bits
from image_helpers import (
    logger,                    # same logger name: "student_palace.uploads"
    read_limited,              # size-limited reader with stream reset
    FILE_SIZE_LIMIT_BYTES,     # 5 MB
    ALLOWED_MIMES,             # {"image/jpeg","image/png","image/webp","image/gif"}
)

# === Config ===
MAX_FILES_PER_HOUSE_PLANS = 5
# Relative under /static
FLOORPLAN_UPLOAD_DIR = "uploads/floorplans"
# Brand light purple (from CSS var --brand-light)
BRAND_LIGHT_RGB = (125, 63, 198)

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

# ---------- Image processing ----------
def _load_font_for_width(img_width: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # scale ~1/16 of width, clamped
    font_size = max(14, img_width // 16)
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf",
        "DejaVuSans.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, font_size)
        except Exception:
            pass
    return ImageFont.load_default()

def _open_image_safely(buf: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(buf))
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    # ensure RGB for a consistent pipeline
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg.convert("RGB")
    else:
        im = im.convert("RGB")
    return im

def _resize_longest(im: Image.Image, bound: int = 1600) -> Image.Image:
    w, h = im.size
    longest = max(w, h)
    if longest <= bound:
        return im.copy()
    scale = bound / float(longest)
    return im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

def _pad_to_canvas(im: Image.Image, canvas_color = BRAND_LIGHT_RGB) -> Image.Image:
    """
    No cropping. If image is portrait or ultra-wide, add padding bars so
    the *canvas* longest side is 1600 and the short side is the natural scaled size.
    Bars use brand-light purple.
    """
    w, h = im.size
    # Choose a simple target: longest side already limited to 1600 by _resize_longest.
    # Keep that, and center the image in a canvas that matches the resized dimensions,
    # adding bars only if we want a minimum short side (optional). Here we don't enforce
    # a fixed aspect; we only add bars if needed to avoid edge issues in very thin images.
    # For consistency with house pipeline, we only return im (no bars) unless the image
    # becomes extremely thin; then we add small margins to ensure watermark visibility.
    MIN_SHORT = 400  # give some room for the watermark to never clip
    if min(w, h) >= MIN_SHORT:
        return im

    if w < MIN_SHORT:
        canvas_w = MIN_SHORT
        canvas_h = h
    else:
        canvas_w = w
        canvas_h = MIN_SHORT

    canvas = Image.new("RGB", (canvas_w, canvas_h), canvas_color)
    x = (canvas_w - w) // 2
    y = (canvas_h - h) // 2
    canvas.paste(im, (x, y))
    return canvas

def _watermark_top_left(im: Image.Image, text: str = "Student Palace") -> Image.Image:
    """
    Always place watermark at top-left with padding, shadow + white text,
    with clamping to avoid clipping even on narrow canvases.
    """
    out = im.copy().convert("RGBA")
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = out.size
    font = _load_font_for_width(w)

    # dynamic padding from width, with clamps
    pad = max(12, w // 80)
    x, y = pad, pad

    # Draw shadow then text
    draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 120))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 170))

    return Image.alpha_composite(out, overlay).convert("RGB")

def _process_plan_image(buf: bytes) -> Tuple[bytes, int, int]:
    """
    Open → auto-rotate → RGB → resize longest to 1600 → optional padding (brand purple) →
    top-left watermark → save as optimized JPEG.
    Returns (jpeg_bytes, width, height).
    """
    im = _open_image_safely(buf)
    im = _resize_longest(im, 1600)
    im = _pad_to_canvas(im, BRAND_LIGHT_RGB)
    im = _watermark_top_left(im, "Student Palace")

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
