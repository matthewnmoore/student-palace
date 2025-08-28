from __future__ import annotations

import io
import os
from datetime import datetime as dt
from typing import List, Tuple, Dict, Any

from flask import request, render_template, redirect, url_for, flash
from PIL import Image, ImageDraw, ImageOps

from utils import current_landlord_id, require_landlord, owned_house_or_none
from db import get_db
from . import landlord_bp

# ---------------------------------
# Config / Paths
# ---------------------------------

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")
# Files are saved under STATIC/uploads/houses and served at /static/uploads/houses
UPLOAD_DIR = os.path.join(STATIC_ROOT, "uploads", "houses")

MAX_FILES_PER_HOUSE = 5
FILE_SIZE_LIMIT_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}  # we re-encode to JPEG
MAX_BOUND = 1600  # longest edge after resize
WATERMARK_TEXT = "Student Palace"


# ---------------------------------
# Helpers
# ---------------------------------

def _rand_token(n: int = 6) -> str:
    import secrets
    return secrets.token_hex(max(3, n // 2))


def _ensure_upload_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _enforce_house_limit(conn, hid: int) -> Tuple[int, int, bool]:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM house_images WHERE house_id=?", (hid,)
    ).fetchone()
    current = int(row["c"]) if row else 0
    remaining = max(0, MAX_FILES_PER_HOUSE - current)
    return current, remaining, current < MAX_FILES_PER_HOUSE


def _collect_files_from_request() -> List:
    fs = request.files
    files: List = []
    for key in ("photos", "photos[]", "photo", "file"):
        if key in fs:
            items = fs.getlist(key)
            if not isinstance(items, (list, tuple)):
                items = [items]
            files.extend([x for x in items if getattr(x, "filename", "")])
    return files


def _read_limited(file_storage) -> bytes | None:
    data = file_storage.read(FILE_SIZE_LIMIT_BYTES + 1)
    file_storage.stream.seek(0)
    return data if data else None


def _open_image_safely(buf: bytes) -> Image.Image:
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


def _resize_longest(im: Image.Image, bound: int = MAX_BOUND) -> Image.Image:
    w, h = im.size
    longest = max(w, h)
    if longest <= bound:
        return im.copy()
    scale = bound / float(longest)
    return im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def _watermark(im: Image.Image) -> Image.Image:
    out = im.copy().convert("RGBA")
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = out.size
    pad = max(12, w // 80)
    text = WATERMARK_TEXT
    bbox = draw.textbbox((0, 0), text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = w - tw - pad
    y = h - th - pad
    draw.text((x + 1, y + 1), text, fill=(0, 0, 0, 100))   # shadow
    draw.text((x, y), text, fill=(255, 255, 255, 150))     # text
    composed = Image.alpha_composite(out, overlay)
    return composed.convert("RGB")


def _process_image(buf: bytes) -> Image.Image:
    im = _open_image_safely(buf)
    im = _resize_longest(im, MAX_BOUND)
    im = _watermark(im)
    return im


def _save_jpeg(im: Image.Image, path: str) -> None:
    im.save(path, format="JPEG", quality=85, optimize=True, progressive=True)


def _table_columns(conn, table: str) -> List[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _insert_house_image_row(conn, hid: int, fname: str, cols: List[str]) -> None:
    """
    Insert into house_images honoring existing columns.
    - If `file_path` exists (and is NOT NULL in your DB), set it to 'uploads/houses/<fname>'.
    - If `filename` or `file_name` exist, set them too (same base name).
    """
    has_file_path = "file_path" in cols
    has_file_name = "file_name" in cols
    has_filename  = "filename"  in cols
    if not (has_file_path or has_file_name or has_filename):
        raise RuntimeError("house_images must include one of: file_path, file_name, filename")

    values: Dict[str, Any] = {"house_id": hid}

    # What we store in DB:
    # - file_path should be path *relative to /static*: 'uploads/houses/<fname>'
    rel_path = f"uploads/houses/{fname}"

    if has_file_path:
        values["file_path"] = rel_path
    if has_file_name:
        values["file_name"] = fname
    if has_filename:
        values["filename"] = fname

    if "is_primary" in cols:
        r = conn.execute(
            "SELECT COUNT(*) AS c FROM house_images WHERE house_id=? AND is_primary=1",
            (hid,),
        ).fetchone()
        values["is_primary"] = 1 if (r and int(r["c"]) == 0) else 0

    if "sort_order" in cols:
        r2 = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS mx FROM house_images WHERE house_id=?",
            (hid,),
        ).fetchone()
        values["sort_order"] = (int(r2["mx"]) if r2 else 0) + 1

    if "created_at" in cols:
        values["created_at"] = dt.utcnow().isoformat()

    field_order = [c for c in ("house_id", "file_path", "file_name", "filename", "is_primary", "sort_order", "created_at") if c in values]
    placeholders = ",".join(["?"] * len(field_order))
    sql = f"INSERT INTO house_images ({', '.join(field_order)}) VALUES ({placeholders})"
    params = tuple(values[c] for c in field_order)
    conn.execute(sql, params)


def _select_images(conn, hid: int, cols: List[str]) -> List[Dict[str, Any]]:
    # Choose a filename expression that works with any schema
    # (prefer file_path if present, otherwise filename/file_name)
    if "file_path" in cols:
        fname_expr = "file_path"  # e.g., 'uploads/houses/<fname>'
        is_path = True
    elif "filename" in cols and "file_name" in cols:
        fname_expr = "COALESCE(filename, file_name)"
        is_path = False
    elif "filename" in cols:
        fname_expr = "filename"
        is_path = False
    elif "file_name" in cols:
        fname_expr = "file_name"
        is_path = False
    else:
        return []

    order_primary = "is_primary DESC," if "is_primary" in cols else ""
    order_sort = "sort_order ASC," if "sort_order" in cols else ""

    rows = conn.execute(
        f"""
        SELECT id,
               {fname_expr} AS fname
          FROM house_images
         WHERE house_id=?
         ORDER BY {order_primary} {order_sort} id ASC
        """,
        (hid,),
    ).fetchall()

    out = []
    for r in rows:
        raw = r["fname"]
        # Convert DB value to a browser path the template expects.
        # - If it already is a relative path like 'uploads/houses/x.jpg', prefix 'static/'.
        # - If it's just a file name 'x.jpg', build 'static/uploads/houses/x.jpg'.
        if is_path:
            web_path = f"static/{raw.lstrip('/')}"  # ensure it starts with 'static/'
        else:
            web_path = f"static/uploads/houses/{raw}"
        out.append({
            "id": r["id"],
            "is_primary": False,  # optional; not used in your template right now
            "file_path": web_path,  # template uses "/{{ img.file_path }}"
        })
    return out


# ---------------------------------
# Views
# ---------------------------------

@landlord_bp.route("/landlord/houses/<int:hid>/photos")
def house_photos(hid):
    r = require_landlord()
    if r:
        return r

    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    cols = _table_columns(conn, "house_images")
    images = _select_images(conn, hid, cols)
    _, remaining, _ = _enforce_house_limit(conn, hid)
    conn.close()

    return render_template(
        "house_photos.html",
        house=house,
        images=images,
        max_images=MAX_FILES_PER_HOUSE,
        remaining=remaining
    )


@landlord_bp.route("/landlord/houses/<int:hid>/photos/upload", methods=["POST"])
def house_photos_upload(hid):
    r = require_landlord()
    if r:
        return r

    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    current, remaining, can_add = _enforce_house_limit(conn, hid)
    if not can_add:
        conn.close()
        flash(f"You’ve reached the photo limit for this house ({MAX_FILES_PER_HOUSE}).", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    try:
        _ensure_upload_dir()
    except Exception:
        conn.close()
        flash("Server storage isn’t available right now. Please try again later.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    files = _collect_files_from_request()
    if not files:
        conn.close()
        flash("Please choose a photo to upload.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    files = files[:remaining]
    accepted = 0
    skipped_msgs: List[str] = []
    cols = _table_columns(conn, "house_images")

    for f in files:
        mimetype = (f.mimetype or "").lower()
        if mimetype not in ALLOWED_MIMES:
            skipped_msgs.append(f"“{f.filename}” is not a supported image type.")
            continue

        data = _read_limited(f)
        if data is None:
            skipped_msgs.append(f"Could not read “{f.filename}”.")
            continue
        if len(data) > FILE_SIZE_LIMIT_BYTES:
            skipped_msgs.append(f"“{f.filename}” is larger than 5 MB.")
            continue

        try:
            processed = _process_image(data)
        except Exception:
            skipped_msgs.append(f"“{f.filename}” doesn’t look like a valid image.")
            continue

        ts = dt.utcnow().strftime("%Y%m%d%H%M%S")
        fname = f"house{hid}_{ts}_{_rand_token()}.jpg"
        abs_path = os.path.join(UPLOAD_DIR, fname)
        try:
            _save_jpeg(processed, abs_path)
        except Exception:
            skipped_msgs.append(f"Couldn’t save “{f.filename}”.")
            continue

        try:
            _insert_house_image_row(conn, hid, fname, cols)
            accepted += 1
        except Exception as e:
            # Undo saved file if DB write fails
            try:
                os.remove(abs_path)
            except Exception:
                pass
            print("[ERROR] insert house_image failed:", repr(e))
            skipped_msgs.append(f"Saved “{f.filename}”, but couldn’t record it. Skipped.")

    try:
        if accepted:
            conn.commit()
        else:
            conn.rollback()
    except Exception as e:
        print("[ERROR] commit/rollback:", repr(e))
        flash("Something went wrong finalizing the upload.", "error")
    finally:
        conn.close()

    if accepted:
        flash(f"Uploaded {accepted} photo{'s' if accepted != 1 else ''}.", "ok")
    for m in skipped_msgs:
        flash(m, "error")

    return redirect(url_for("landlord.house_photos", hid=hid))


@landlord_bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/primary", methods=["POST"])
def house_photos_primary(hid, img_id):
    r = require_landlord()
    if r:
        return r

    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    cols = _table_columns(conn, "house_images")
    if "is_primary" not in cols:
        conn.close()
        flash("Your database doesn’t support primary photos yet.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    row = conn.execute(
        "SELECT id FROM house_images WHERE id=? AND house_id=?", (img_id, hid)
    ).fetchone()
    if not row:
        conn.close()
        flash("Photo not found.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    try:
        conn.execute("UPDATE house_images SET is_primary=0 WHERE house_id=?", (hid,))
        conn.execute("UPDATE house_images SET is_primary=1 WHERE id=? AND house_id=?", (img_id, hid))
        conn.commit()
        flash("Primary photo set.", "ok")
    except Exception as e:
        conn.rollback()
        print("[ERROR] set primary:", repr(e))
        flash("Could not set primary photo.", "error")
    finally:
        conn.close()

    return redirect(url_for("landlord.house_photos", hid=hid))


@landlord_bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/delete", methods=["POST"])
def house_photos_delete(hid, img_id):
    r = require_landlord()
    if r:
        return r

    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    cols = _table_columns(conn, "house_images")

    # Expression to get stored file reference from DB
    if "file_path" in cols:
        fname_expr = "file_path"   # e.g., 'uploads/houses/x.jpg'
        is_path = True
    elif "filename" in cols and "file_name" in cols:
        fname_expr = "COALESCE(filename, file_name)"
        is_path = False
    elif "filename" in cols:
        fname_expr = "filename"
        is_path = False
    elif "file_name" in cols:
        fname_expr = "file_name"
        is_path = False
    else:
        conn.close()
        flash("DB table misconfigured (no filename column).", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    had_primary = False
    stored = None
    try:
        img = conn.execute(
            f"SELECT id, {fname_expr} AS f"
            + (", is_primary" if "is_primary" in cols else "")
            + " FROM house_images WHERE id=? AND house_id=?",
            (img_id, hid)
        ).fetchone()
        if not img:
            conn.close()
            flash("Photo not found.", "error")
            return redirect(url_for("landlord.house_photos", hid=hid))

        stored = img["f"]
        if "is_primary" in cols:
            had_primary = bool(int(img["is_primary"]))

        conn.execute("DELETE FROM house_images WHERE id=? AND house_id=?", (img_id, hid))
        conn.commit()
        conn.close()

        # Map DB value to absolute path on disk
        if is_path:
            rel = stored.lstrip("/")  # 'uploads/houses/x.jpg'
        else:
            rel = f"uploads/houses/{stored}"
        abs_path = os.path.join(STATIC_ROOT, rel)
        try:
            os.remove(abs_path)
        except Exception:
            pass

        if had_primary and "is_primary" in cols:
            conn2 = get_db()
            try:
                order_expr = "sort_order" if "sort_order" in cols else "id"
                nxt = conn2.execute(
                    f"SELECT id FROM house_images WHERE house_id=? ORDER BY {order_expr} ASC, id ASC LIMIT 1",
                    (hid,)
                ).fetchone()
                if nxt:
                    conn2.execute("UPDATE house_images SET is_primary=1 WHERE id=?", (nxt["id"],))
                    conn2.commit()
            except Exception:
                conn2.rollback()
            finally:
                conn2.close()

        flash("Photo deleted.", "ok")
    except Exception as e:
        conn.rollback()
        conn.close()
        print("[ERROR] delete photo:", repr(e))
        flash("Could not delete that photo.", "error")

    return redirect(url_for("landlord.house_photos", hid=hid))
