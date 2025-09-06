
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

# ------------ FS helpers ------------

def ensure_upload_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)

def static_rel_path(filename: str) -> str:
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

def _load_font_for_width(img_width: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
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

def watermark(im: Image.Image, text: str = WATERMARK_TEXT) -> Image.Image:
    """
    Always-visible bottom-right watermark:
    - Fits text inside the image by shrinking the font if needed
    - Clamps coordinates to stay on-canvas
    - Adds a soft contrast panel under the text for visibility
    """
    if not text:
        text = "Student Palace"

    base = im.convert("RGBA")
    w, h = base.size

    font = _load_font_for_width(w)

    def _measure(draw, t, f):
        try:
            bx = draw.textbbox((0, 0), t, font=f)
            return bx[2] - bx[0], bx[3] - bx[1]
        except Exception:
            return draw.textsize(t, font=f)

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    max_w = int(w * 0.90)
    max_h = int(h * 0.25)

    tw, th = _measure(draw, text, font)
    min_px = 12
    guard = 0
    while (tw > max_w or th > max_h) and getattr(font, "size", 16) > min_px and guard < 40:
        new_size = max(min_px, int(getattr(font, "size", 16) * 0.9))
        try:
            candidates = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "DejaVuSans-Bold.ttf",
                "DejaVuSans.ttf",
            ]
            loaded = None
            for p in candidates:
                try:
                    loaded = ImageFont.truetype(p, new_size)
                    break
                except Exception:
                    continue
            font = loaded or ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
        tw, th = _measure(draw, text, font)
        guard += 1

    pad = max(12, w // 80)
    x = w - tw - pad
    y = h - th - pad

    if x < pad:
        x = pad
    if y < pad:
        y = pad

    panel_pad = max(6, pad // 2)
    panel = [x - panel_pad, y - panel_pad, x + tw + panel_pad, y + th + panel_pad]
    draw.rectangle(panel, fill=(0, 0, 0, 80))

    draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 160))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 170))

    composed = Image.alpha_composite(base, overlay)
    return composed.convert("RGB")

def process_image(buf: bytes) -> Image.Image:
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
        "file_path": r["file_path"],
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
