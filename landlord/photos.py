# landlord/photos.py
from __future__ import annotations

import time, logging
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none
from . import bp

from image_helpers import (
    accept_upload, select_images, set_primary, delete_image,
    MAX_FILES_PER_HOUSE,
    assert_house_images_schema,
)

logger = logging.getLogger("student_palace.uploads")

@bp.route("/landlord/houses/<int:hid>/photos", methods=["GET", "POST"])
def house_photos(hid: int):
    """
    GET  -> show existing photos + upload form
    POST -> accept MULTIPLE file uploads (safe batch)
    """
    # login/ownership checks
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

    # guard: ensure DB schema is what we expect before doing anything
    try:
        assert_house_images_schema(conn)
    except Exception as e:
        conn.close()
        flash(f"Photo feature is not available: {e}", "error")
        return render_template(
            "house_photos.html",
            house=house,
            images=[],
            max_images=MAX_FILES_PER_HOUSE,
        )

    if request.method == "POST":
        batch_start = time.perf_counter()

        # MULTI: files come from input name="photos" multiple
        files = request.files.getlist("photos")
        # Some browsers include an empty item; filter those
        files = [f for f in files if getattr(f, "filename", "").strip()]

        if not files:
            images = select_images(conn, hid)
            conn.close()
            flash("Please choose at least one photo to upload.", "error")
            return render_template(
                "house_photos.html",
                house=house,
                images=images,
                max_images=MAX_FILES_PER_HOUSE,
            )

        # Enforce house limit at the batch level
        existing = len(select_images(conn, hid))
        remaining = max(0, MAX_FILES_PER_HOUSE - existing)
        if remaining <= 0:
            conn.close()
            flash(f"House already has {MAX_FILES_PER_HOUSE} photos.", "error")
            return redirect(url_for("landlord.house_photos", hid=hid))

        # Only try up to remaining slots
        to_process = files[:remaining]

        successes = 0
        errors = []
        for f in to_process:
            ok, msg = accept_upload(conn, hid, f, enforce_limit=False)  # batch limit enforced above
            if ok:
                successes += 1
            else:
                errors.append(f"{getattr(f, 'filename', 'file')}: {msg}")

        # commit/rollback once per batch
        try:
            if successes:
                conn.commit()
            else:
                conn.rollback()
        except Exception:
            flash("Could not finalize the upload.", "error")
            conn.close()
            return redirect(url_for("landlord.house_photos", hid=hid))

        # Batch timing log
        elapsed = time.perf_counter() - batch_start
        logger.info(
            f"[UPLOAD-BATCH] house={hid} tried={len(files)} processed={len(to_process)} "
            f"success={successes} errors={len(errors)} elapsed={elapsed:.2f}s"
        )

        # Build a friendly summary
        skipped_due_to_limit = len(files) - len(to_process)
        parts = []
        if successes:
            parts.append(f"Uploaded {successes} file{'s' if successes != 1 else ''}.")
        if errors:
            parts.append(f"Skipped {len(errors)} due to errors.")
        if skipped_due_to_limit > 0:
            parts.append(f"{skipped_due_to_limit} not processed (house limit {MAX_FILES_PER_HOUSE}).")

        if successes:
            flash(" ".join(parts), "ok")
        else:
            # No success at all: show details as error
            detail = " ".join(parts) if parts else "Upload failed."
            flash(detail, "error")
            for e in errors:
                flash(e, "error")

        conn.close()
        return redirect(url_for("landlord.house_photos", hid=hid))

    # GET: list images
    images = select_images(conn, hid)
    conn.close()
    return render_template(
        "house_photos.html",
        house=house,
        images=images,
        max_images=MAX_FILES_PER_HOUSE,
    )

@bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/primary", methods=["POST"])
def house_photos_primary(hid: int, img_id: int):
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
        assert_house_images_schema(conn)
        set_primary(conn, hid, img_id)
        conn.commit()
        flash("Primary photo set.", "ok")
    except Exception:
        conn.rollback()
        flash("Could not set primary photo.", "error")
    finally:
        conn.close()

    return redirect(url_for("landlord.house_photos", hid=hid))

@bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/delete", methods=["POST"])
def house_photos_delete(hid: int, img_id: int):
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
        assert_house_images_schema(conn)
        fname = delete_image(conn, hid, img_id)
        if not fname:
            conn.rollback()
            conn.close()
            flash("Photo not found.", "error")
            return redirect(url_for("landlord.house_photos", hid=hid))

        conn.commit()  # DB first
        conn.close()

        # after DB success, try to remove the file (best effort)
        from image_helpers import file_abs_path
        import os
        try:
            os.remove(file_abs_path(fname))
        except Exception:
            pass

        flash("Photo deleted.", "ok")
    except Exception:
        conn.rollback()
        conn.close()
        flash("Could not delete photo.", "error")

    return redirect(url_for("landlord.house_photos", hid=hid))


# (these helpers were present in your current file; leaving untouched)
from utils import clean_bool
from db import get_db as _get_db  # alias to avoid shadowing

def room_form_values(request):
    name = (request.form.get("name") or "").strip()
    ensuite = clean_bool("ensuite")
    bed_size = (request.form.get("bed_size") or "").strip()
    tv = clean_bool("tv")
    desk_chair = clean_bool("desk_chair")
    wardrobe = clean_bool("wardrobe")
    chest_drawers = clean_bool("chest_drawers")
    lockable_door = clean_bool("lockable_door")
    wired_internet = clean_bool("wired_internet")
    room_size = (request.form.get("room_size") or "").strip()
    errors = []
    if not name:
        errors.append("Room name is required.")
    if bed_size not in ("Single","Small double","Double","King"):
        errors.append("Please choose a valid bed size.")
    return ({
        "name": name, "ensuite": ensuite, "bed_size": bed_size, "tv": tv,
        "desk_chair": desk_chair, "wardrobe": wardrobe, "chest_drawers": chest_drawers,
        "lockable_door": lockable_door, "wired_internet": wired_internet, "room_size": room_size
    }, errors)

def room_counts(conn, hid):
    row = conn.execute("SELECT bedrooms_total FROM houses WHERE id=?", (hid,)).fetchone()
    max_rooms = int(row["bedrooms_total"]) if row else 0
    cnt = conn.execute("SELECT COUNT(*) AS c FROM rooms WHERE house_id=?", (hid,)).fetchone()["c"]
    return max_rooms, int(cnt)

