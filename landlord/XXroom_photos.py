# landlord/room_photos.py
from __future__ import annotations

import time, logging
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none
from . import bp

from image_helpers_rooms import (
    accept_upload_room, select_images_room, set_primary_room, delete_image_room,
    MAX_FILES_PER_ROOM,
    assert_room_images_schema,
)

logger = logging.getLogger("student_palace.uploads")


@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/photos", methods=["GET", "POST"])
def room_photos(hid: int, rid: int):
    """
    GET  -> show existing room photos + upload form
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

    room = conn.execute("SELECT * FROM rooms WHERE id=? AND house_id=?", (rid, hid)).fetchone()
    if not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    # guard: ensure DB schema
    try:
        assert_room_images_schema(conn)
    except Exception as e:
        conn.close()
        flash(f"Room photo feature not available: {e}", "error")
        return render_template(
            "room_photos.html",
            house=house,
            room=room,
            images=[],
            max_images=MAX_FILES_PER_ROOM,
        )

    if request.method == "POST":
        batch_start = time.perf_counter()

        files = request.files.getlist("photos")
        files = [f for f in files if getattr(f, "filename", "").strip()]
        if not files:
            images = select_images_room(conn, rid)
            conn.close()
            flash("Please choose at least one photo to upload.", "error")
            return render_template(
                "room_photos.html",
                house=house,
                room=room,
                images=images,
                max_images=MAX_FILES_PER_ROOM,
            )

        # enforce limit
        existing = len(select_images_room(conn, rid))
        remaining = max(0, MAX_FILES_PER_ROOM - existing)
        if remaining <= 0:
            conn.close()
            flash(f"Room already has {MAX_FILES_PER_ROOM} photos.", "error")
            return redirect(url_for("landlord.room_photos", hid=hid, rid=rid))

        to_process = files[:remaining]
        successes, errors = 0, []
        for f in to_process:
            ok, msg = accept_upload_room(conn, rid, f, enforce_limit=False)
            if ok:
                successes += 1
            else:
                errors.append(f"{getattr(f, 'filename', 'file')}: {msg}")

        try:
            if successes:
                conn.commit()
            else:
                conn.rollback()
        except Exception:
            flash("Could not finalize the upload.", "error")
            conn.close()
            return redirect(url_for("landlord.room_photos", hid=hid, rid=rid))

        elapsed = time.perf_counter() - batch_start
        logger.info(
            f"[UPLOAD-BATCH] room={rid} tried={len(files)} processed={len(to_process)} "
            f"success={successes} errors={len(errors)} elapsed={elapsed:.2f}s"
        )

        skipped_due_to_limit = len(files) - len(to_process)
        parts = []
        if successes:
            parts.append(f"Uploaded {successes} file{'s' if successes != 1 else ''}.")
        if errors:
            parts.append(f"Skipped {len(errors)} due to errors.")
        if skipped_due_to_limit > 0:
            parts.append(f"{skipped_due_to_limit} not processed (room limit {MAX_FILES_PER_ROOM}).")

        if successes:
            flash(" ".join(parts), "ok")
        else:
            detail = " ".join(parts) if parts else "Upload failed."
            flash(detail, "error")
            for e in errors:
                flash(e, "error")

        conn.close()
        return redirect(url_for("landlord.room_photos", hid=hid, rid=rid))

    # GET
    images = select_images_room(conn, rid)
    conn.close()
    return render_template(
        "room_photos.html",
        house=house,
        room=room,
        images=images,
        max_images=MAX_FILES_PER_ROOM,
    )


@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/photos/<int:img_id>/primary", methods=["POST"])
def room_photos_primary(hid: int, rid: int, img_id: int):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    room = conn.execute("SELECT * FROM rooms WHERE id=? AND house_id=?", (rid, hid)).fetchone()
    if not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    try:
        assert_room_images_schema(conn)
        set_primary_room(conn, rid, img_id)
        conn.commit()
        flash("Primary photo set.", "ok")
    except Exception:
        conn.rollback()
        flash("Could not set primary photo.", "error")
    finally:
        conn.close()

    return redirect(url_for("landlord.room_photos", hid=hid, rid=rid))


@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/photos/<int:img_id>/delete", methods=["POST"])
def room_photos_delete(hid: int, rid: int, img_id: int):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    room = conn.execute("SELECT * FROM rooms WHERE id=? AND house_id=?", (rid, hid)).fetchone()
    if not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    try:
        assert_room_images_schema(conn)
        fname = delete_image_room(conn, rid, img_id)
        if not fname:
            conn.rollback()
            conn.close()
            flash("Photo not found.", "error")
            return redirect(url_for("landlord.room_photos", hid=hid, rid=rid))

        conn.commit()
        conn.close()

        # cleanup disk
        from image_helpers_rooms import file_abs_path_room
        import os
        try:
            os.remove(file_abs_path_room(fname))
        except Exception:
            pass

        flash("Photo deleted.", "ok")
    except Exception:
        conn.rollback()
        conn.close()
        flash("Could not delete photo.", "error")

    return redirect(url_for("landlord.room_photos", hid=hid, rid=rid))
