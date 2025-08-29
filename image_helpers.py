# image_helpers.py
from __future__ import annotations

import io, os
from datetime import datetime as dt
from typing import Dict, List, Tuple, Optional

from PIL import Image, ImageDraw, ImageOps, ImageFont  # requires Pillow in requirements.txt

# ------------ Config ------------
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")
UPLOAD_DIR = os.path.join(STATIC_ROOT, "uploads", "houses")  # served at /static/uploads/houses

MAX_FILES_PER_HOUSE = 5
FILE_SIZE_LIMIT_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

# Resize bound for longest edge
MAX_BOUND = 1600

# Watermark settings
WATERMARK_TEXT = "Student Palace"
WATERMARK_REL_SIZE = 1 / 16.0       # text height ≈ image_width * this (increase to make larger)
WATERMARK_ALPHA = 190               # 0..255 (text)
WATERMARK_SHADOW_ALPHA = 120        # 0..255 (shadow)
WATERMARK_MARGIN_RATIO = 0.03       # margin as fraction of width (e.g., 3%)

# Optional: put a font in your repo and point here for consistent rendering, e.g. static/fonts/Inter-SemiBold.ttf
WATERMARK_FONT_PATH = None  # os.path.join(STATIC_ROOT, "fonts", "Inter-SemiBold.ttf")

# ------------ FS helpers ------------

def ensure_upload_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)

def static_rel_path(filename: str) -> str:
    # store WITHOUT a leading slash; render with url_for('static', filename=...)
    return f"uploads/houses/{filename}"

def file_abs_path(filename: str) -> str:
    return os.path.join(UPLOAD_DIR, filename)

# ------------ Image helpers ------------

def _rand_token(n: int = 6) -> str:
    import secrets
    return secrets.token_hex(max(3, n // 2))

def read_limited(file_storage) -> Optional[bytes]:
    data = file_storage.read(FILE_SIZE_LIMIT_BYTES + 1)
    file_storage.stream.seek(0)
    return data if data else None

def open_image_safely(buf: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(buf))
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg.convert("RGB")
    else:
        im = im.convert("RGB")
    return im

def resize_longest(im: Image.Image, bound: int = MAX_BOUND) -> Image.Image:
    w, h = im.size
    longest = max(w, h)
    if longest <= bound:
        return im.copy()
    scale = bound / float(longest)
    return im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

def _get_font(img_width: int):
    """
    Return a PIL ImageFont instance sized relative to image width.
    Tries a few common TTFs; falls back to default bitmap (small).
    """
    target_px = max(14, int(img_width * WATERMARK_REL_SIZE))
    candidates = []
    if WATERMARK_FONT_PATH:
        candidates.append(WATERMARK_FONT_PATH)

    # Common system fonts
    candidates.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ])

    for path in candidates:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, target_px)
        except Exception:
            pass

    # Fallback (bitmap font; won’t scale but avoids crash)
    return ImageFont.load_default()

def watermark(im: Image.Image, text: str = WATERMARK_TEXT) -> Image.Image:
    """
    Draw a bottom-right watermark that scales with image width and has a soft shadow.
    """
    out = im.convert("RGBA")
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    w, h = out.size
    font = _get_font(w)

    # Measure text
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # Margin from edges
    margin = max(8, int(w * WATERMARK_MARGIN_RATIO))
    x = w - tw - margin
    y = h - th - margin

    # Shadow (soft offset)
    shadow_offset = max(1, int(w * 0.004))  # ~0.4% of width
    draw.text((x + shadow_offset, y + shadow_offset), text,
              font=font, fill=(0, 0, 0, WATERMARK_SHADOW_ALPHA))
    # Foreground
    draw.text((x, y), text, font=font, fill=(255, 255, 255, WATERMARK_ALPHA))

    composed = Image.alpha_composite(out, overlay)
    return composed.convert("RGB")

def process_image(buf: bytes) -> Image.Image:
    # Resize then watermark (order matters so text stays crisp)
    return watermark(resize_longest(open_image_safely(buf), MAX_BOUND))

def save_jpeg(im: Image.Image, abs_path: str) -> Tuple[int, int, int]:
    im.save(abs_path, format="JPEG", quality=85, optimize=True, progressive=True)
    w, h = im.size
    byt = os.path.getsize(abs_path)
    return w, h, byt

# ------------ DB schema guard ------------

REQUIRED_COLS = {
    "id","house_id","file_name","filename","file_path",
    "width","height","bytes","is_primary","sort_order","created_at"
}

def get_cols(conn, table: str) -> List[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

def assert_house_images_schema(conn) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='house_images'"
    ).fetchone()
    if not row:
        raise RuntimeError("house_images table missing")
    cols = set(get_cols(conn, "house_images"))
    missing = REQUIRED_COLS - cols
    if missing:
        raise RuntimeError(f"house_images schema missing columns: {sorted(missing)}")

# ------------ DB operations ------------

def count_for_house(conn, hid: int) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) AS c FROM house_images WHERE house_id=?", (hid,)
    ).fetchone()["c"])

def next_sort_order(conn, hid: int) -> int:
    r = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS mx FROM house_images WHERE house_id=?",
        (hid,)
    ).fetchone()
    return (int(r["mx"]) if r else 0) + 1

def ensure_primary_flag(conn, hid: int) -> int:
    r = conn.execute(
        "SELECT COUNT(*) AS c FROM house_images WHERE house_id=? AND is_primary=1",
        (hid,)
    ).fetchone()
    return 1 if (r and int(r["c"]) == 0) else 0

def insert_image_row(conn, hid: int, fname: str, width: int, height: int, bytes_: int) -> None:
    file_path = static_rel_path(fname)
    values = (
        hid, fname, fname, file_path, width, height, bytes_,
        ensure_primary_flag(conn, hid), next_sort_order(conn, hid), dt.utcnow().isoformat()
    )
    conn.execute("""
        INSERT INTO house_images(
          house_id, file_name, filename, file_path, width, height, bytes,
          is_primary, sort_order, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
    """, values)

def select_images(conn, hid: int) -> List[Dict]:
    rows = conn.execute("""
        SELECT id,
               COALESCE(filename, file_name) AS filename,
               file_path, width, height, bytes,
               is_primary, sort_order, created_at
          FROM house_images
         WHERE house_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (hid,)).fetchall()
    return [{
        "id": r["id"],
        "is_primary": int(r["is_primary"]) == 1,
        "file_path": r["file_path"],      # relative path under /static
        "filename": r["filename"],
        "width": int(r["width"]),
        "height": int(r["height"]),
        "bytes": int(r["bytes"]),
        "sort_order": int(r["sort_order"]),
        "created_at": r["created_at"],
    } for r in rows]

def set_primary(conn, hid: int, img_id: int) -> None:
    conn.execute("UPDATE house_images SET is_primary=0 WHERE house_id=?", (hid,))
    conn.execute("UPDATE house_images SET is_primary=1 WHERE id=? AND house_id=?", (img_id, hid))

def delete_image(conn, hid: int, img_id: int) -> Optional[str]:
    row = conn.execute("""
        SELECT id, COALESCE(filename, file_name) AS filename
          FROM house_images
         WHERE id=? AND house_id=?""", (img_id, hid)).fetchone()
    if not row:
        return None
    fname = row["filename"]
    conn.execute("DELETE FROM house_images WHERE id=? AND house_id=?", (img_id, hid))
    return fname

# ------------ One-shot upload flow ------------

def accept_upload(conn, hid: int, file_storage, *, enforce_limit: bool = True) -> Tuple[bool, str]:
    """
    Returns (ok, message). Saves to disk + DB or reports a reason.
    """
    if enforce_limit and count_for_house(conn, hid) >= MAX_FILES_PER_HOUSE:
        return False, f"House already has {MAX_FILES_PER_HOUSE} photos."

    mimetype = (file_storage.mimetype or "").lower()
    if mimetype not in ALLOWED_MIMES:
        return False, "Unsupported image type."

    data = read_limited(file_storage)
    if not data:
        return False, "Could not read the file."
    if len(data) > FILE_SIZE_LIMIT_BYTES:
        return False, "File is larger than 5 MB."

    try:
        im = process_image(data)
    except Exception:
        return False, "File is not a valid image."

    ensure_upload_dir()
    ts = dt.utcnow().strftime("%Y%m%d%H%M%S")
    fname = f"house{hid}_{ts}_{_rand_token()}.jpg"
    abs_path = file_abs_path(fname)

    try:
        w, h, byt = save_jpeg(im, abs_path)
    except Exception:
        return False, "Server storage is not available."

    try:
        assert_house_images_schema(conn)
        insert_image_row(conn, hid, fname, w, h, byt)
    except Exception as e:
        try:
            os.remove(abs_path)
        except Exception:
            pass
        return False, f"Couldn’t record image in DB: {e}"

    return True, "Uploaded"
