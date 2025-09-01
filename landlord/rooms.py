# landlord/room_photos.py
from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt
from db import get_db
from utils import require_landlord, current_landlord_id, owned_house_or_none
from . import bp

# Image helper wrappers specific to room images
# (You added this file earlier)
from image_helpers_rooms import (
    assert_room_images_schema,
    select_room_images,
    accept_upload_room,
    set_primary_room_image,
    delete_room_image,
)

def _owned_room_or_none(conn, hid: int, rid: int, lid: int):
    """Verify the landlord owns the house and the room belongs to that house."""
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        return None, None
    room = conn.execute(
        "SELECT * FROM rooms WHERE id=? AND house_id=?",
        (rid, hid)
    ).fetchone()
    if not room:
        return house, None
    return house, room

@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/photos", methods=["GET"])
def room_photos(hid, rid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()

    conn = get_db()
    house, room = _owned_room_or_none(conn, hid, rid, lid)
    if not house or not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    # Ensure table exists (add-only guard) and fetch current images
    assert_room_images_schema(conn)
    images = select_room_images(conn, rid)
    conn.close()

    return render_template(
        "room_photos.html",
        house=house,
        room=room,
        images=images,
    )

@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/photos", methods=["POST"])
def room_photos_upload(hid, rid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()

    conn = get_db()
    house, room = _owned_room_or_none(conn, hid, rid, lid)
    if not house or not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    assert_room_images_schema(conn)

    file = request.files.get("file")
    ok, msg = accept_upload_room(conn, rid, file, enforce_limit=True)
    if ok:
        conn.commit()
        flash("Uploaded.", "ok")
    else:
        conn.rollback()
        flash(msg or "Upload failed.", "error")

    conn.close()
    return redirect(url_for("landlord.room_photos", hid=hid, rid=rid))

@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/photos/<int:img_id>/primary", methods=["POST"])
def room_photos_set_primary(hid, rid, img_id):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()

    conn = get_db()
    house, room = _owned_room_or_none(conn, hid, rid, lid)
    if not house or not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    assert_room_images_schema(conn)
    set_primary_room_image(conn, rid, img_id)
    conn.commit()
    conn.close()
    flash("Primary image set.", "ok")
    return redirect(url_for("landlord.room_photos", hid=hid, rid=rid))

@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/photos/<int:img_id>/delete", methods=["POST"])
def room_photos_delete(hid, rid, img_id):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()

    conn = get_db()
    house, room = _owned_room_or_none(conn, hid, rid, lid)
    if not house or not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    assert_room_images_schema(conn)
    fname = delete_room_image(conn, rid, img_id)
    if fname:
        conn.commit()
        flash("Deleted.", "ok")
        # best-effort disk cleanup is handled inside helper; if not, house-keeping can run elsewhere.
    else:
        conn.rollback()
        flash("Image not found.", "error")

    conn.close()
    return redirect(url_for("landlord.room_photos", hid=hid, rid=rid))
