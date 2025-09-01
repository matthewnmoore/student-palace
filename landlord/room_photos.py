# landlord/room_photos.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt

from . import bp  # ← relative import of the shared blueprint (prevents circular import)
from db import get_db
from utils import require_landlord, current_landlord_id, owned_house_or_none

# Room-image helpers (standalone module at project root)
from image_helpers_rooms import (
    assert_room_images_schema,
    select_room_images,
    accept_room_upload,
    set_room_primary,
    delete_room_image,
    file_abs_path_room,
)

def _owned_room_or_none(conn, hid: int, rid: int, lid: int):
    """Ensure the room exists and belongs to the landlord's house."""
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        return None, None
    room = conn.execute(
        "SELECT * FROM rooms WHERE id=? AND house_id=?", (rid, hid)
    ).fetchone()
    if not room:
        return house, None
    return house, room

@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/photos", methods=["GET"])
def room_photos_view(hid, rid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()

    conn = get_db()
    house, room = _owned_room_or_none(conn, hid, rid, lid)
    if not house or not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    # Ensure schema exists (add-only, safe)
    assert_room_images_schema(conn)

    images = select_room_images(conn, rid)
    conn.close()
    return render_template("room_photos.html", house=house, room=room, images=images)

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
    ok, msg = accept_room_upload(conn, rid, file, enforce_limit=True)
    if ok:
        conn.commit()
        flash("Uploaded.", "ok")
    else:
        conn.rollback()
        flash(msg or "Upload failed.", "error")

    conn.close()
    return redirect(url_for("landlord.room_photos_view", hid=hid, rid=rid))

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

    try:
        set_room_primary(conn, rid, img_id)
        conn.commit()
        flash("Primary set.", "ok")
    except Exception as e:
        conn.rollback()
        flash(f"Couldn’t set primary: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("landlord.room_photos_view", hid=hid, rid=rid))

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

    # Delete DB row and remove file on disk
    fname = delete_room_image(conn, rid, img_id)
    if fname:
        try:
            # Remove from disk (best-effort)
            import os
            os.remove(file_abs_path_room(fname))
        except Exception:
            pass
        conn.commit()
        flash("Photo deleted.", "ok")
    else:
        conn.rollback()
        flash("Photo not found.", "error")

    conn.close()
    return redirect(url_for("landlord.room_photos_view", hid=hid, rid=rid))
