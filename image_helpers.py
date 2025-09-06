# image_helpers.py
from __future__ import annotations

import io, os, time, logging
from datetime import datetime as dt
from typing import Dict, List, Tuple, Optional

from PIL import Image, ImageDraw, ImageOps, ImageFont

# ------------ Logging ------------
logger = logging.getLogger("student_palace.uploads")

# ------------ Config ------------
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")
UPLOAD_DIR = os.path.join(STATIC_ROOT, "uploads", "houses")  # served at /static/uploads/houses

MAX_FILES_PER_HOUSE = 5
FILE_SIZE_LIMIT_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_BOUND = 1600
WATERMARK_TEXT = os.environ.get("WATERMARK_TEXT", "Student Palace")

# ---- DEBUG switch: paints a red box where the watermark goes ----
WATERMARK_DEBUG = True  # set to False after testing

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
    # normalize to RGB (drop alpha) so later JPEG save is deterministic
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

def _load_font_for_width(img_width: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # ~6–8% of image width
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
            continue
    return ImageFont.load_default()

def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    """Robust text measurement with fallbacks."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return max(0, bbox[2] - bbox[0]), max(0, bbox[3] - bbox[1])
    except Exception:
        # Fallbacks if textbbox is unavailable/unsupported
        try:
            tw = int(draw.textlength(text, font=font))
        except Exception:
            tw = max(10, len(text) * 7)
        # best effort height guess
        th = getattr(font, "size", 16)
        return max(1, tw), max(10, th)

def watermark(im: Image.Image, text: str = WATERMARK_TEXT) -> Image.Image:
    """
    Compose a watermark (shadow + white text) at bottom-right.
    In DEBUG mode, first draw a semi-transparent red rectangle so we can
    visually confirm overlay/compositing is working.
    """
    out = im.convert("RGBA")
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = out.size
    font = _load_font_for_width(w)

    # padding relative to width
    pad = max(12, w // 80)

    # DEBUG: big red box in the corner to prove compositing path
    if WATERMARK_DEBUG:
        box_w = max(80, w // 5)
        box_h = max(40, h // 10)
        x0 = max(0, w - box_w - pad)
        y0 = max(0, h - box_h - pad)
        x1 = min(w, x0 + box_w)
        y1 = min(h, y0 + box_h)
        draw.rectangle([x0, y0, x1, y1], fill=(255, 0, 0, 120))

    # Measure text robustly
    tw, th = _measure_text(draw, text, font)

    # Clamp width/height of text to image size
    tw = min(tw, max(1, w - 2 * pad))
    th = min(th, max(10, h - 2 * pad))

    # Place bottom-right within bounds
    x = max(pad, w - tw - pad)
    y = max(pad, h - th - pad)

    # Final clamp in case of edge cases
    x = min(max(0, x), max(0, w - tw))
    y = min(max(0, y), max(0, h - th))

    # Draw shadow + text (higher alpha to ensure visibility)
    try:
        draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 240))
    except Exception:
        # As a last resort, draw a thick line as a visible marker
        draw.line([(x, y), (min(w - 1, x + tw), y)], fill=(255, 255, 255, 240), width=3)

    composed = Image.alpha_composite(out, overlay)
    return composed.convert("RGB")

def process_image(buf: bytes) -> Image.Image:
    # order is important: open → resize → watermark
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

# ------------ One-shot upload flow with timing logs ------------

def accept_upload(conn, hid: int, file_storage, *, enforce_limit: bool = True) -> Tuple[bool, str]:
    """
    Returns (ok, message). Saves to disk + DB or reports a reason.
    Emits timing logs to stdout (Render Logs) at INFO level.
    """
    start = time.perf_counter()
    original_name = getattr(file_storage, "filename", "") or "unnamed"
    mimetype = (getattr(file_storage, "mimetype", None) or "").lower()

    if enforce_limit and count_for_house(conn, hid) >= MAX_FILES_PER_HOUSE:
        logger.info(f"[UPLOAD] house={hid} name={original_name!r} mime={mimetype} skipped=limit_reached")
        return False, f"House already has {MAX_FILES_PER_HOUSE} photos."

    if mimetype not in ALLOWED_MIMES:
        logger.info(f"[UPLOAD] house={hid} name={original_name!r} mime={mimetype} skipped=bad_mime")
        return False, "Unsupported image type."

    data = read_limited(file_storage)
    if not data:
        logger.info(f"[UPLOAD] house={hid} name={original_name!r} mime={mimetype} skipped=empty_read")
        return False, "Could not read the file."
    if len(data) > FILE_SIZE_LIMIT_BYTES:
        logger.info(f"[UPLOAD] house={hid} name={original_name!r} mime={mimetype} skipped=too_large size={len(data)}")
        return False, "File is larger than 5 MB."

    try:
        im = process_image(data)
    except Exception:
        logger.exception(f"[UPLOAD] house={hid} name={original_name!r} mime={mimetype} failed=invalid_image")
        return False, "File is not a valid image."

    ensure_upload_dir()
    ts = dt.utcnow().strftime("%Y%m%d%H%M%S")
    fname = f"house{hid}_{ts}_{_rand_token()}.jpg"
    abs_path = file_abs_path(fname)

    try:
        w, h, byt = save_jpeg(im, abs_path)
    except Exception:
        logger.exception(f"[UPLOAD] house={hid} name={original_name!r} mime={mimetype} failed=fs_write")
        return False, "Server storage is not available."

    try:
        assert_house_images_schema(conn)
        insert_image_row(conn, hid, fname, w, h, byt)
    except Exception as e:
        try:
            os.remove(abs_path)
        except Exception:
            pass
        logger.exception(f"[UPLOAD] house={hid} name={original_name!r} mime={mimetype} failed=db_insert")
        return False, f"Couldn’t record image in DB: {e}"

    elapsed = time.perf_counter() - start
    logger.info(
        f"[UPLOAD] house={hid} name={original_name!r} saved={fname!r} mime={mimetype} "
        f"size_bytes={byt} dims={w}x{h} elapsed={elapsed:.2f}s"
    )
    return True, "Uploaded"
