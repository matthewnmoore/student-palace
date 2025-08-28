from __future__ import annotations

import io
import os
import random
import string
from datetime import datetime as dt
from typing import List, Tuple

from flask import request, render_template, redirect, url_for, flash
from PIL import Image, ImageDraw, ImageOps

from utils import current_landlord_id, require_landlord, owned_house_or_none
from db import get_db
from . import landlord_bp


# -------------------------------
# Config
# -------------------------------

# We save under: static/uploads/houses  (served by Flask static files)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")
UPLOAD_SUBPATH = os.path.join("uploads", "houses")
UPLOAD_DIR = os.path.join(STATIC_ROOT, UPLOAD_SUBPATH)

# Limits & processing
MAX_FILES_PER_HOUSE = 5
FILE_SIZE_LIMIT_BYTES = 5 * 1024 * 1024  # 5 MB per file
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_BOUND = 1600  # longest edge after resize
WATERMARK_TEXT = "Student Palace"  # subtle text watermark (bottom-right)


# -------------------------------
# Helpers
# -------------------------------

def _rand_token(n: int = 5) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _ensure_upload_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _next_sort_start(conn, hid: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS mx FROM house_images WHERE house_id=?",
        (hid,),
    ).fetchone()
    return int(row["mx"]) + 1


def _house_counts(conn, hid: int) -> Tuple[int, int, bool]:
    """Return (current_count, remaining, can_add)."""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM house_images WHERE house_id=?", (hid,)
    ).fetchone()
    current = int(row["c"]) if row else 0
    remaining = max(0, MAX_FILES_PER_HOUSE - current)
    return current, remaining, current < MAX_FILES_PER_HOUSE


def _open_image_safely(buf: bytes) -> Image.Image:
    """Open with Pillow, auto-orient using EXIF, return RGB image."""
    image = Image.open(io.BytesIO(buf))
    try:
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass
    # Convert to RGB for consistent JPEG saving (flatten alpha if needed)
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        bg = Image.new("RGBA", image.size, (255, 255, 255, 255))
        bg.alpha_composite(image)
        image = bg.convert("RGB")
    else:
        image = image.convert("RGB")
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
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    w, h = base.size
    pad = max(12, w // 80)
    text = WATERMARK_TEXT

    # Measure text with default bitmap font (keeps deps minimal)
    bbox = draw.textbbox((0, 0), text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = w - text_w - pad
    y = h - text_h - pad

    # Shadow + main text
    draw.text((x + 1, y + 1), text, fill=(0, 0, 0, 90))
    draw.text((x, y), text, fill=(255, 255, 255, 140))

    out = Image.alpha_composite(base, overlay)
    return out.convert("RGB")


def _process_image(buf: bytes) -> Image.Image:
    img = _open_image_safely(buf)
    img = _resize(img)
    img = _watermark(img)
    return img


def _save_processed_jpeg(image: Image.Image, dest_path: str) -> None:
    image.save(dest_path, format="JPEG", quality=85, optimize=True, progressive=True)


def _has_primary(conn, hid: int) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM house_images WHERE house_id=? AND is_primary=1",
        (hid,),
    ).fetchone()
    return bool(row and int(row["c"]) > 0)


def _collect_files_from_request() -> List:
    """
    Support multiple common field names and multi-file inputs.
    Prefers 'photos[]', but supports 'photos', 'photo', 'file' as fallbacks.
    """
    files = []
    for key in ("photos[]", "photos", "photo", "file"):
        if key in request.files:
            files.extend(request.files.getlist(key))
    # Keep only items that have a filename
    return [f for f in files if getattr(f, "filename", "")]


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
    images = [{
        "id": r_["id"],
        "is_primary": bool(r_["is_primary"]),
        # IMPORTANT: these live under /static/..., so use url_for('static', filename=...)
        "file_path": f"{UPLOAD_SUBPATH}/{r_['filename']}",
    } for r_ in rows]

    remaining = max(0, max_images - len(images))
    conn.close()

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
    Handle uploads: accept multiple files (photos[]), enforce size/type,
    resize + watermark, save to static/uploads/houses, and insert DB rows.
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

    current, remaining, can_add = _house_counts(conn, hid)
    if not can_add:
        conn.close()
        flash(f"You’ve reached the photo limit for this house ({MAX_FILES_PER_HOUSE}).", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    # Collect files
    files = _collect_files_from_request()
    if not files:
        conn.close()
        flash("Please choose a photo to upload.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    # Ensure upload dir exists
    try:
        _ensure_upload_dir()
    except Exception:
        conn.close()
        flash("Server storage isn’t available right now. Please try again later.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    # Process up to remaining files
    files = files[:remaining]
    next_sort = _next_sort_start(conn, hid)
    already_has_primary = _has_primary(conn, hid)

    accepted = 0
    rejected: List[str] = []

    try:
        for f in files:
            # MIME/type check (best-effort; we’ll still try to open with Pillow below)
            mimetype = (f.mimetype or "").lower()
            if mimetype not in ALLOWED_MIMES:
                rejected.append(f"“{f.filename}” isn’t a supported image type.")
                continue

            # Size cap
            data = f.read(FILE_SIZE_LIMIT_BYTES + 1)
            if not data:
                rejected.append(f"Couldn’t read “{f.filename}”.")
                continue
            if len(data) > FILE_SIZE_LIMIT_BYTES:
                rejected.append(f"“{f.filename}” is larger than 5 MB.")
                continue

            # Pillow processing
            try:
                processed = _process_image(data)
            except Exception:
                rejected.append(f"“{f.filename}” doesn’t look like a valid image.")
                continue

            # Unique jpg filename
            ts = dt.utcnow().strftime("%Y%m%d%H%M%S")
            fname = f"house{hid}_{ts}_{_rand_token()}.jpg"
            abs_path = os.path.join(UPLOAD_DIR, fname)

            try:
                _save_processed_jpeg(processed, abs_path)
            except Exception:
                rejected.append(f"Couldn’t save “{f.filename}”.")
                continue

            # Insert DB row
            try:
                is_primary = 0
                if not already_has_primary and accepted == 0:
                    # Make the first successful insert primary if none exists yet
                    is_primary = 1
                    already_has_primary = True

                conn.execute(
                    """
                    INSERT INTO house_images (house_id, filename, is_primary, sort_order, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (hid, fname, is_primary, next_sort, dt.utcnow().isoformat())
                )
                next_sort += 1
                accepted += 1
            except Exception:
                # best-effort cleanup
                try:
                    os.remove(abs_path)
                except Exception:
                    pass
                rejected.append(f"Saved “{f.filename}”, but couldn’t record it. Skipped.")
                continue

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
    for msg in rejected:
        flash(msg, "error")

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
            "SELECT filename, is_primary FROM house_images WHERE id=? AND house_id=?",
            (img_id, hid)
        ).fetchone()
        if not row:
            conn.close()
            flash("Photo not found.", "error")
            return redirect(url_for("landlord.house_photos", hid=hid))

        filename = row["filename"]
        was_primary = int(row["is_primary"]) == 1

        conn.execute("DELETE FROM house_images WHERE id=? AND house_id=?", (img_id, hid))
        conn.commit()

        # If primary was deleted, promote the lowest sort_order
        if was_primary:
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

        conn.close()

        # best-effort file removal
        try:
            os.remove(os.path.join(UPLOAD_DIR, filename))
        except Exception:
            pass

        flash("Photo deleted.", "ok")
    except Exception:
        conn.close()
        flash("Could not delete that photo.", "error")

    return redirect(url_for("landlord.house_photos", hid=hid))
