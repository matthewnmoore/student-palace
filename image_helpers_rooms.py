# image_helpers_rooms.py
from __future__ import annotations

import io, os, time, logging
from datetime import datetime as dt
from typing import Dict, List, Tuple, Optional

from PIL import Image, ImageDraw, ImageOps, ImageFont  # keep parity with house helper

# ------------ Logging ------------
logger = logging.getLogger("student_palace.uploads.rooms")

# ------------ Config (rooms) ------------
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")
UPLOAD_DIR = os.path.join(STATIC_ROOT, "uploads", "rooms")  # served at /static/uploads/rooms

MAX_FILES_PER_ROOM = 5
FILE_SIZE_LIMIT_BYTES = 5 * 1024 * 1024  # 5 MB (same as houses)
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_BOUND = 1600
WATERMARK_TEXT = os.environ.get("WATERMARK_TEXT", "Student Palace")

# ------------ FS helpers ------------

def ensure_upload_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)

def static_rel_path(filename: str) -> str:
    # store WITHOUT a leading slash; render with url_for('static', filename=...)
    return f"uploads/rooms/{filename}"

def file_abs_path(filename: str) -> str:
    return os.path.join(UPLOAD_DIR, filename)

# ------------ Image helpers (parity with house images) ------------

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
            pass
    return ImageFont.load_default()

def watermark(im: Image.Image, text: str = WATERMARK_TEXT) -> Image.Image:
    out = im.copy().convert("RGBA")
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = out.size
    font = _load_font_for_width(w)

    # measure with font
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    pad = max(12, w // 80)
    x = max(pad, w - tw - pad)
    y = max(pad, h - th - pad)

    # soft shadow + white text
    draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 120))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 170))

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

# ------------ DB schema guard (rooms) ------------

REQUIRED_COLS_ROOMS = {
    "id","room_id","file_name","filename","file_path",
    "width","height","bytes","is_primary","sort_order","created_at"
}

def get_cols(conn, table: str) -> List[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

def assert_room_images_schema(conn) -> None:
    """
    Safe, add-only schema ensure for `room_images`.
    Creates the table if missing, and adds any missing columns with defaults.
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
    # Add-only guards (handles environments where table existed but lacked a column)
    def _safe_add(col_sql: str):
        try:
            conn.execute(f"ALTER TABLE room_images ADD COLUMN {col_sql}")
        except Exception:
            pass

    # Mirror the house_images required set
    _safe_add("file_name TEXT NOT NULL DEFAULT ''")
    _safe_add("filename TEXT NOT NULL DEFAULT ''")
    _safe_add("file_path TEXT NOT NULL DEFAULT ''")
    _safe_add("width INTEGER NOT NULL DEFAULT 0")
    _safe_add("height INTEGER NOT NULL DEFAULT 0")
    _safe_add("bytes INTEGER NOT NULL DEFAULT 0")
    _safe_add("is_primary INTEGER NOT NULL DEFAULT 0")
    _safe_add("sort_order INTEGER NOT NULL DEFAULT 0")
    _safe_add("created_at TEXT NOT NULL DEFAULT ''")

    # Sanity check for required columns (raise if still missing after guards)
    cols = set(get_cols(conn, "room_images"))
    missing = REQUIRED_COLS_ROOMS - cols
    if missing:
        raise RuntimeError(f"room_images schema missing columns: {sorted(missing)}")

# ------------ DB operations (rooms) ------------

def count_for_room(conn, rid: int) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) AS c FROM room_images WHERE room_id=?", (rid,)
    ).fetchone()["c"])

def next_sort_order(conn, rid: int) -> int:
    r = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS mx FROM room_images WHERE room_id=?",
        (rid,)
    ).fetchone()
    return (int(r["mx"]) if r else 0) + 1

def ensure_primary_flag(conn, rid: int) -> int:
    r = conn.execute(
        "SELECT COUNT(*) AS c FROM room_images WHERE room_id=? AND is_primary=1",
        (rid,)
    ).fetchone()
    return 1 if (r and int(r["c"]) == 0) else 0

def insert_image_row(conn, rid: int, fname: str, width: int, height: int, bytes_: int) -> None:
    file_path = static_rel_path(fname)
    values = (
        rid, fname, fname, file_path, width, height, bytes_,
        ensure_primary_flag(conn, rid), next_sort_order(conn, rid), dt.utcnow().isoformat()
    )
    conn.execute("""
        INSERT INTO room_images(
          room_id, file_name, filename, file_path, width, height, bytes,
          is_primary, sort_order, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
    """, values)

def select_images(conn, rid: int) -> List[Dict]:
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
        "file_path": r["file_path"],      # relative path under /static
        "filename": r["filename"],
        "width": int(r["width"]),
        "height": int(r["height"]),
        "bytes": int(r["bytes"]),
        "sort_order": int(r["sort_order"]),
        "created_at": r["created_at"],
    } for r in rows]

def set_primary(conn, rid: int, img_id: int) -> None:
    conn.execute("UPDATE room_images SET is_primary=0 WHERE room_id=?", (rid,))
    conn.execute("UPDATE room_images SET is_primary=1 WHERE id=? AND room_id=?", (img_id, rid))

def delete_image(conn, rid: int, img_id: int) -> Optional[str]:
    row = conn.execute("""
        SELECT id, COALESCE(filename, file_name) AS filename
          FROM room_images
         WHERE id=? AND room_id=?""", (img_id, rid)).fetchone()
    if not row:
        return None
    fname = row["filename"]
    conn.execute("DELETE FROM room_images WHERE id=? AND room_id=?", (img_id, rid))
    return fname

# ------------ One-shot upload flow with timing logs (rooms) ------------

def accept_upload(conn, rid: int, file_storage, *, enforce_limit: bool = True) -> Tuple[bool, str]:
    """
    Returns (ok, message). Saves to disk + DB or reports a reason.
    Emits timing logs to stdout (Render Logs) at INFO level.
    """
    start = time.perf_counter()
    original_name = getattr(file_storage, "filename", "") or "unnamed"
    mimetype = (getattr(file_storage, "mimetype", None) or "").lower()

    if enforce_limit and count_for_room(conn, rid) >= MAX_FILES_PER_ROOM:
        logger.info(f"[ROOM_UPLOAD] room={rid} name={original_name!r} mime={mimetype} skipped=limit_reached")
        return False, f"Room already has {MAX_FILES_PER_ROOM} photos."

    if mimetype not in ALLOWED_MIMES:
        logger.info(f"[ROOM_UPLOAD] room={rid} name={original_name!r} mime={mimetype} skipped=bad_mime")
        return False, "Unsupported image type."

    data = read_limited(file_storage)
    if not data:
        logger.info(f"[ROOM_UPLOAD] room={rid} name={original_name!r} mime={mimetype} skipped=empty_read")
        return False, "Could not read the file."
    if len(data) > FILE_SIZE_LIMIT_BYTES:
        logger.info(f"[ROOM_UPLOAD] room={rid} name={original_name!r} mime={mimetype} skipped=too_large size={len(data)}")
        return False, "File is larger than 5 MB."

    try:
        im = process_image(data)
    except Exception:
        logger.exception(f"[ROOM_UPLOAD] room={rid} name={original_name!r} mime={mimetype} failed=invalid_image")
        return False, "File is not a valid image."

    ensure_upload_dir()
    ts = dt.utcnow().strftime("%Y%m%d%H%M%S")
    fname = f"room{rid}_{ts}_{_rand_token()}.jpg"
    abs_path = file_abs_path(fname)

    try:
        w, h, byt = save_jpeg(im, abs_path)
    except Exception:
        logger.exception(f"[ROOM_UPLOAD] room={rid} name={original_name!r} mime={mimetype} failed=fs_write")
        return False, "Server storage is not available."

    try:
        assert_room_images_schema(conn)
        insert_image_row(conn, rid, fname, w, h, byt)
    except Exception as e:
        try:
            os.remove(abs_path)
        except Exception:
            pass
        logger.exception(f"[ROOM_UPLOAD] room={rid} name={original_name!r} mime={mimetype} failed=db_insert")
        return False, f"Couldn’t record image in DB: {e}"

    elapsed = time.perf_counter() - start
    logger.info(
        f"[ROOM_UPLOAD] room={rid} name={original_name!r} saved={fname!r} mime={mimetype} "
        f"size_bytes={byt} dims={w}x{h} elapsed={elapsed:.2f}s"
    )
    return True, "Uploaded"
