from __future__ import annotations

import io
import os
import secrets
from datetime import datetime as dt
from typing import Iterable, List

from flask import render_template, redirect, url_for, flash, request
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont, ImageOps  # requires Pillow

from . import landlord_bp  # IMPORTANT: relative import avoids circulars
from utils import current_landlord_id, require_landlord, owned_house_or_none
from db import get_db


# -------------------------------
# Config
# -------------------------------
MAX_IMAGE_MB = 5  # hard limit for incoming file (user feedback + bandwidth)
MAIN_MAX_W = 1600
THUMB_W = 400
UPLOAD_ROOT = "uploads"
HOUSE_SUBDIR = "houses"  # uploads/houses
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif"}  # we always write JPEG output

WATERMARK_TEXT = "Student Palace"
WATERMARK_MARGIN = 12  # px from edges
WATERMARK_ALPHA = 110   # 0..255 (lower = more transparent)
WATERMARK_SHADOW_ALPHA = 160


# -------------------------------
# Helpers
# -------------------------------
def _ensure_dirs():
    os.makedirs(os.path.join(UPLOAD_ROOT, HOUSE_SUBDIR), exist_ok=True)


def _get_files_from_request() -> List:
    """
    Support common field names:
    - <input name="photos" multiple>
    - <input name="photos[]" multiple>
    - <input name="photo">
    """
    f = request.files
    files = []
    for key in ("photos", "photos[]", "photo", "file"):
        if key in f:
            items = f.getlist(key)
            # some browsers submit single file without list
            if not isinstance(items, (list, tuple)):
                items = [items]
            files.extend([x for x in items if getattr(x, "filename", "")])
    return files


def _reject_if_too_big(file_storage) -> str | None:
    """
    Reject > 5MB *per file*. We peek size by reading into memory once (bounded),
    then rewind for Pillow. With 5MB cap, this is acceptable.
    """
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_IMAGE_MB * 1024 * 1024:
        return f"“{file_storage.filename}” is larger than {MAX_IMAGE_MB} MB."
    return None


def _ext_allowed(filename: str) -> bool:
    ext = (filename.rsplit(".", 1)[-1].lower() if "." in filename else "")
    return ext in ALLOWED_EXT


def _open_image_bgrace(file_storage) -> Image.Image:
    """Open image safely, honoring EXIF orientation."""
    data = file_storage.read()
    file_storage.stream.seek(0)
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im)
    # Convert to RGB for consistent JPEG write (flatten alpha if present)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg.convert("RGB")
    else:
        im = im.convert("RGB")
    return im


def _resize_to_width(im: Image.Image, target_w: int) -> Image.Image:
    w, h = im.size
    if w <= target_w:
        return im.copy()
    scale = target_w / float(w)
    target_h = int(h * scale)
    return im.resize((target_w, target_h), Image.LANCZOS)


def _apply_watermark(im: Image.Image) -> Image.Image:
    """Bottom-right text watermark with soft shadow."""
    out = im.copy()
    draw = ImageDraw.Draw(out)

    # choose font size proportional to width (fallback to default if truetype not found)
    w, h = out.size
    font_size = max(14, int(w * 0.035))  # ~3.5% of width
    try:
        # Try a common font path (environment dependent). If not present, use default.
        font = ImageFont.truetype("DejaVuSans.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    text = WATERMARK_TEXT
    tw, th = draw.textbbox((0, 0), text, font=font)[2:]  # width,height

    x = w - tw - WATERMARK_MARGIN
    y = h - th - WATERMARK_MARGIN

    # Shadow
    shadow_pos = (x + 1, y + 1)
    draw.text(
        shadow_pos, text, font=font,
        fill=(0, 0, 0, WATERMARK_SHADOW_ALPHA)
    )
    # Foreground (semi-transparent white)
    draw.text(
        (x, y), text, font=font,
        fill=(255, 255, 255, WATERMARK_ALPHA)
    )
    return out


def _save_jpeg(im: Image.Image, dest_path: str):
    im.save(dest_path, format="JPEG", quality=85, optimize=True, progressive=True)


def _unique_base(hid: int) -> str:
    # Example: house15_20240828_8f3a1c2d
    return f"house{hid}_{dt.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"


def _insert_house_image(conn, hid: int, filename: str, make_primary_if_none: bool):
    # Determine sort_order = current max + 1
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS m FROM house_images WHERE house_id=?",
        (hid,)
    ).fetchone()
    next_sort = int(row["m"]) + 1 if row else 1

    is_primary = 0
    if make_primary_if_none:
        r2 = conn.execute(
            "SELECT COUNT(*) AS c FROM house_images WHERE house_id=? AND is_primary=1",
            (hid,)
        ).fetchone()
        is_primary = 1 if (r2 and int(r2["c"]) == 0) else 0

    conn.execute(
        """
        INSERT INTO house_images(house_id, filename, is_primary, sort_order)
        VALUES (?,?,?,?)
        """,
        (hid, filename, is_primary, next_sort)
    )


def _delete_house_image_files(filename: str):
    main_path = os.path.join(UPLOAD_ROOT, HOUSE_SUBDIR, filename)
    base, _ = os.path.splitext(filename)
    thumb_path = os.path.join(UPLOAD_ROOT, HOUSE_SUBDIR, f"{base}_thumb.jpg")
    for p in (main_path, thumb_path):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


# -------------------------------
# Views
# -------------------------------
@landlord_bp.route("/landlord/houses/<int:hid>/photos")
def house_photos(hid):
    """Render the photos page for a house (now with real data)."""
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

    rows = conn.execute(
        """
        SELECT id, filename, is_primary
          FROM house_images
         WHERE house_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
        """,
        (hid,)
    ).fetchall()
    conn.close()

    images = [{
        "id": r["id"],
        "is_primary": bool(r["is_primary"]),
        "file_path": f"{UPLOAD_ROOT}/{HOUSE_SUBDIR}/{r['filename']}",
    } for r in rows]

    max_images = 5
    remaining = max(0, max_images - len(images))

    return render_template(
        "house_photos.html",
        house=house,
        images=images,
        max_images=max_images,
        remaining=remaining
    )


@landlord_bp.route("/landlord/houses/<int:hid>/photos/upload", methods=["POST"])
def house_photos_upload(hid):
    """
    Accept upload(s), enforce 5MB limit, resize, watermark, thumbnail, save,
    and record rows in house_images.
    """
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

    # Limit total count to 5
    current_count = conn.execute(
        "SELECT COUNT(*) AS c FROM house_images WHERE house_id=?",
        (hid,)
    ).fetchone()["c"]
    max_images = 5
    remaining_slots = max(0, max_images - int(current_count))
    if remaining_slots <= 0:
        conn.close()
        flash("You’ve reached the photo limit for this house (5).", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    files = _get_files_from_request()
    if not files:
        conn.close()
        flash("Please choose at least one image to upload.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    _ensure_dirs()
    accepted = 0
    rejected_msgs: List[str] = []

    try:
        for file_storage in files[:remaining_slots]:
            fname = secure_filename(file_storage.filename or "")
            if not fname or not _ext_allowed(fname):
                rejected_msgs.append(f"“{file_storage.filename}” isn’t a supported image type.")
                continue

            big_msg = _reject_if_too_big(file_storage)
            if big_msg:
                rejected_msgs.append(big_msg)
                continue

            # Process
            try:
                im = _open_image_bgrace(file_storage)
            except Exception:
                rejected_msgs.append(f"“{file_storage.filename}” isn’t a valid image.")
                continue

            # Create outputs
            main = _resize_to_width(im, MAIN_MAX_W)
            main = _apply_watermark(main)

            thumb = _resize_to_width(im, THUMB_W)

            # Unique base name; always save as JPEG
            base = _unique_base(hid)
            main_name = f"{base}.jpg"
            thumb_name = f"{base}_thumb.jpg"

            main_path = os.path.join(UPLOAD_ROOT, HOUSE_SUBDIR, main_name)
            thumb_path = os.path.join(UPLOAD_ROOT, HOUSE_SUBDIR, thumb_name)

            try:
                _save_jpeg(main, main_path)
                _save_jpeg(thumb, thumb_path)
            except Exception:
                # if writing fails, skip and attempt cleanup
                _delete_house_image_files(main_name)
                rejected_msgs.append(f"Couldn’t save “{file_storage.filename}”.")
                continue

            # Insert DB row (we store only the main file base; thumb is implied)
            _insert_house_image(conn, hid, main_name, make_primary_if_none=True)
            accepted += 1

        conn.commit()
    except Exception as e:
        conn.rollback()
        print("[ERROR] house_photos_upload:", e)
        flash("Something went wrong while uploading. Please try again.", "error")
        conn.close()
        return redirect(url_for("landlord.house_photos", hid=hid))

    conn.close()

    if accepted:
        flash(f"Uploaded {accepted} photo{'s' if accepted != 1 else ''}.", "ok")
    if rejected_msgs:
        for m in rejected_msgs:
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

    row = conn.execute(
        "SELECT id FROM house_images WHERE id=? AND house_id=?",
        (img_id, hid)
    ).fetchone()
    if not row:
        conn.close()
        flash("Photo not found.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    try:
        conn.execute("UPDATE house_images SET is_primary=0 WHERE house_id=?", (hid,))
        conn.execute("UPDATE house_images SET is_primary=1 WHERE id=? AND house_id=?", (img_id, hid))
        conn.commit()
        flash("Primary photo updated.", "ok")
    except Exception as e:
        conn.rollback()
        print("[ERROR] house_photos_primary:", e)
        flash("Could not update primary photo.", "error")
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

    img = conn.execute(
        "SELECT id, filename, is_primary FROM house_images WHERE id=? AND house_id=?",
        (img_id, hid)
    ).fetchone()
    if not img:
        conn.close()
        flash("Photo not found.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    try:
        # Remove files
        _delete_house_image_files(img["filename"])
        # Remove DB record
        conn.execute("DELETE FROM house_images WHERE id=? AND house_id=?", (img_id, hid))
        conn.commit()

        # If it was primary, promote the next (lowest sort_order)
        if int(img["is_primary"]) == 1:
            nxt = conn.execute(
                """
                SELECT id FROM house_images
                WHERE house_id=?
                ORDER BY sort_order ASC, id ASC
                LIMIT 1
                """,
                (hid,)
            ).fetchone()
            if nxt:
                conn.execute("UPDATE house_images SET is_primary=1 WHERE id=?", (nxt["id"],))
                conn.commit()

        flash("Photo deleted.", "ok")
    except Exception as e:
        conn.rollback()
        print("[ERROR] house_photos_delete:", e)
        flash("Could not delete photo.", "error")
    finally:
        conn.close()

    return redirect(url_for("landlord.house_photos", hid=hid))
