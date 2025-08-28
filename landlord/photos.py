from __future__ import annotations

import io
import os
import random
import string
from datetime import datetime as dt

from flask import request, render_template, redirect, url_for, flash
from PIL import Image, ImageDraw

from utils import current_landlord_id, require_landlord, owned_house_or_none
from db import get_db
from . import landlord_bp


# -------------------------------
# Config
# -------------------------------

# Absolute path to /uploads/houses (create if missing)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads", "houses")

# Limits & processing
MAX_FILES_PER_HOUSE = 5
FILE_SIZE_LIMIT_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_BOUND = 1600  # longest edge after resize
WATERMARK_TEXT = "Student Palace"  # simple, unobtrusive text watermark


# -------------------------------
# Helpers
# -------------------------------

def _rand_token(n: int = 5) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _ensure_upload_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _next_sort_order(conn, hid: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS mx FROM house_images WHERE house_id=?",
        (hid,),
    ).fetchone()
    return int(row["mx"]) + 1


def _enforce_house_limit(conn, hid: int) -> tuple[int, int, bool]:
    """Return (current_count, remaining, can_add)."""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM house_images WHERE house_id=?", (hid,)
    ).fetchone()
    current = int(row["c"]) if row else 0
    remaining = max(0, MAX_FILES_PER_HOUSE - current)
    return current, remaining, current < MAX_FILES_PER_HOUSE


def _open_image_safely(buf: bytes) -> Image.Image:
    """Open image with Pillow and transpose according to EXIF orientation."""
    image = Image.open(io.BytesIO(buf))
    # Pillow >= 6.0: ImageOps.exif_transpose (avoid import to keep deps minimal)
    try:
        from PIL import ImageOps
        image = ImageOps.exif_transpose(image)
    except Exception:
        # fallback: if no EXIF or anything goes wrong, continue with original
        pass
    return image


def _resize(image: Image.Image) -> Image.Image:
    w, h = image.size
    longest = max(w, h)
    if longest <= MAX_BOUND:
        return image
    scale = MAX_BOUND / float(longest)
    new_size = (int(w * scale), int(h * scale))
    return image.resize(new_size, Image.LANCZOS)


def _watermark(image: Image.Image) -> Image.Image:
    """Apply a small semi-transparent text watermark bottom-right."""
    # ensure RGBA for compositing
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # heuristics for size/padding based on image width
    w, h = base.size
    pad = max(12, w // 80)         # e.g. 1600px -> 20px padding
    # approximate font size using default bitmap font metrics: draw.textbbox will scale with stroke width
    # we won't rely on truetype to avoid bundling a font; just use default and a subtle stroke
    text = WATERMARK_TEXT
    bbox = draw.textbbox((0, 0), text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # bottom-right position
    x = w - text_w - pad
    y = h - text_h - pad

    # draw a faint shadow to improve contrast
    draw.text((x + 1, y + 1), text, fill=(0, 0, 0, 90))
    # then the main text, semi-opaque white
    draw.text((x, y), text, fill=(255, 255, 255, 140))

    out = Image.alpha_composite(base, overlay)
    return out.convert("RGB")  # save as JPEG


def _process_image(buf: bytes) -> Image.Image:
    img = _open_image_safely(buf)
    img = _resize(img)
    img = _watermark(img)
    return img


def _save_processed_jpeg(image: Image.Image, dest_path: str) -> None:
    image.save(dest_path, format="JPEG", quality=85, optimize=True, progressive=True)


# -------------------------------
# Views
# -------------------------------

@landlord_bp.route("/landlord/houses/<int:hid>/photos")
def house_photos(hid):
    """Render the photos page for a house."""
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

    rows = conn.execute("""
        SELECT id, filename, is_primary
          FROM house_images
         WHERE house_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (hid,)).fetchall()

    max_images = MAX_FILES_PER_HOUSE
    current_count = len(rows)
    images = [{
        "id": r_["id"],
        "is_primary": bool(r_["is_primary"]),
        "file_path": f"uploads/houses/{r_['filename']}",
    } for r_ in rows]

    conn.close()

    remaining = max(0, max_images - current_count)
    return render_template(
        "house_photos.html",
        house=house,
        images=images,
        max_images=max_images,
        remaining=remaining
    )


@landlord_bp.route("/landlord/houses/<int:hid>/photos/upload", methods=["POST"])
def house_photos_upload(hid):
    """Handle upload: validate, resize, watermark, save, DB insert."""
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

    # Enforce per-house image limit
    _, remaining, can_add = _enforce_house_limit(conn, hid)
    if not can_add:
        conn.close()
        flash(f"You’ve reached the photo limit for this house ({MAX_FILES_PER_HOUSE}).", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    # Ensure upload directory exists
    try:
        _ensure_upload_dir()
    except Exception:
        conn.close()
        flash("Server storage isn’t available right now. Please try again later.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    # Get file
    file = request.files.get("photo")
    if not file or file.filename == "":
        conn.close()
        flash("Please choose a photo to upload.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    # MIME check
    mimetype = (file.mimetype or "").lower()
    if mimetype not in ALLOWED_MIMES:
        conn.close()
        flash("Unsupported image type. Please upload a JPG, PNG, or WebP.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    # Size limit (read into memory up to limit+1)
    data = file.read(FILE_SIZE_LIMIT_BYTES + 1)
    if not data:
        conn.close()
        flash("Could not read the uploaded file.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))
    if len(data) > FILE_SIZE_LIMIT_BYTES:
        conn.close()
        flash("That file is too large. Max size is 5 MB.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    # Process with Pillow: auto-orient, resize, watermark
    try:
        processed = _process_image(data)
    except Exception:
        conn.close()
        flash("That doesn’t look like a valid image file.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    # Build unique filename (we always save as JPEG after processing)
    ts = dt.utcnow().strftime("%Y%m%d%H%M%S")
    fname = f"house{hid}_{ts}_{_rand_token()}.jpg"
    abs_path = os.path.join(UPLOAD_DIR, fname)

    # Save to disk
    try:
        _save_processed_jpeg(processed, abs_path)
    except Exception:
        conn.close()
        flash("We couldn’t save the image. Please try again.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    # Insert DB row
    try:
        sort_order = _next_sort_order(conn, hid)
        conn.execute("""
            INSERT INTO house_images (house_id, filename, is_primary, sort_order, created_at)
            VALUES (?, ?, 0, ?, ?)
        """, (hid, fname, sort_order, dt.utcnow().isoformat()))
        conn.commit()
        conn.close()
    except Exception:
        # best-effort cleanup on DB failure
        try:
            os.remove(abs_path)
        except Exception:
            pass
        flash("Saved the file, but couldn’t record it. Please try again.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    flash("Photo uploaded.", "ok")
    return redirect(url_for("landlord.house_photos", hid=hid))


@landlord_bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/primary", methods=["POST"])
def house_photos_primary(hid, img_id):
    """Mark a photo as primary (simple toggle for the house)."""
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

    try:
        # Ensure the photo belongs to the house
        row = conn.execute(
            "SELECT id FROM house_images WHERE id=? AND house_id=?", (img_id, hid)
        ).fetchone()
        if not row:
            conn.close()
            flash("Photo not found.", "error")
            return redirect(url_for("landlord.house_photos", hid=hid))

        conn.execute("UPDATE house_images SET is_primary=0 WHERE house_id=?", (hid,))
        conn.execute("UPDATE house_images SET is_primary=1 WHERE id=? AND house_id=?", (img_id, hid))
        conn.commit()
        conn.close()
        flash("Primary photo set.", "ok")
    except Exception:
        conn.close()
        flash("Could not set primary photo.", "error")

    return redirect(url_for("landlord.house_photos", hid=hid))


@landlord_bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/delete", methods=["POST"])
def house_photos_delete(hid, img_id):
    """Delete a photo and its file from disk."""
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

    try:
        row = conn.execute(
            "SELECT filename FROM house_images WHERE id=? AND house_id=?", (img_id, hid)
        ).fetchone()
        if not row:
            conn.close()
            flash("Photo not found.", "error")
            return redirect(url_for("landlord.house_photos", hid=hid))

        filename = row["filename"]
        conn.execute("DELETE FROM house_images WHERE id=? AND house_id=?", (img_id, hid))
        conn.commit()
        conn.close()

        # remove file best-effort
        try:
            os.remove(os.path.join(UPLOAD_DIR, filename))
        except Exception:
            pass

        flash("Photo deleted.", "ok")
    except Exception:
        conn.close()
        flash("Could not delete that photo.", "error")

    return redirect(url_for("landlord.house_photos", hid=hid))
