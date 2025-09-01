# landlord/rooms.py
from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt
from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none
from .helpers import room_form_values, room_counts
from . import bp

# ------------------------------
# Existing room CRUD (unchanged)
# ------------------------------
@bp.route("/landlord/houses/<int:hid>/rooms")
def rooms_list(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))
    rows = conn.execute("SELECT * FROM rooms WHERE house_id=? ORDER BY id ASC", (hid,)).fetchall()
    max_rooms, cnt = room_counts(conn, hid)
    conn.close()
    remaining = max(0, max_rooms - cnt)
    can_add = cnt < max_rooms
    return render_template(
        "rooms_list.html",
        house=house,
        rooms=rows,
        can_add=can_add,
        remaining=remaining,
        max_rooms=max_rooms
    )

@bp.route("/landlord/houses/<int:hid>/rooms/new", methods=["GET","POST"])
def room_new(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        return redirect(url_for("landlord.landlord_houses"))

    max_rooms, cnt = room_counts(conn, hid)
    if cnt >= max_rooms:
        conn.close()
        flash(f"You’ve reached the room limit for this house ({max_rooms} bedrooms).", "error")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    if request.method == "POST":
        vals, errors = room_form_values(request)
        if errors:
            for e in errors: flash(e, "error")
            conn.close()
            return render_template("room_form.html", house=house, form=vals, mode="new")
        conn.execute("""
          INSERT INTO rooms(house_id,name,ensuite,bed_size,tv,desk_chair,wardrobe,chest_drawers,lockable_door,wired_internet,room_size,created_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            hid, vals["name"], vals["ensuite"], vals["bed_size"], vals["tv"],
            vals["desk_chair"], vals["wardrobe"], vals["chest_drawers"],
            vals["lockable_door"], vals["wired_internet"], vals["room_size"],
            dt.utcnow().isoformat()
        ))
        conn.commit()
        conn.close()
        flash("Room added.", "ok")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    conn.close()
    return render_template("room_form.html", house=house, form={}, mode="new")

@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/edit", methods=["GET","POST"])
def room_edit(hid, rid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        return redirect(url_for("landlord.landlord_houses"))
    room = conn.execute("SELECT * FROM rooms WHERE id=? AND house_id=?", (rid, hid)).fetchone()
    if not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    if request.method == "POST":
        vals, errors = room_form_values(request)
        if errors:
            for e in errors: flash(e, "error")
            conn.close()
            return render_template("room_form.html", house=house, form=vals, mode="edit", room=room)
        conn.execute("""
          UPDATE rooms SET
            name=?, ensuite=?, bed_size=?, tv=?, desk_chair=?, wardrobe=?, chest_drawers=?, lockable_door=?, wired_internet=?, room_size=?
          WHERE id=? AND house_id=?
        """, (
            vals["name"], vals["ensuite"], vals["bed_size"], vals["tv"], vals["desk_chair"],
            vals["wardrobe"], vals["chest_drawers"], vals["lockable_door"], vals["wired_internet"],
            vals["room_size"], rid, hid
        ))
        conn.commit()
        conn.close()
        flash("Room updated.", "ok")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    form = dict(room)
    conn.close()
    return render_template("room_form.html", house=house, form=form, mode="edit", room=room)

@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/delete", methods=["POST"])
def room_delete(hid, rid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        return redirect(url_for("landlord.landlord_houses"))
    conn.execute("DELETE FROM rooms WHERE id=? AND house_id=?", (rid, hid))
    conn.commit()
    conn.close()
    flash("Room deleted.", "ok")
    return redirect(url_for("landlord.rooms_list", hid=hid))

# ------------------------------
# NEW: Room Photos (add-on)
# ------------------------------
from image_helpers_rooms import (
    assert_room_images_schema, select_room_images, accept_upload_room,
    set_primary_room, delete_room_image, MAX_FILES_PER_ROOM, file_abs_path_room
)

def _owned_room_or_none(conn, rid: int, lid: int):
    # Ensure the room belongs to one of the landlord's houses
    return conn.execute("""
        SELECT r.*, h.id AS house_id
          FROM rooms r
          JOIN houses h ON h.id = r.house_id
         WHERE r.id=? AND h.landlord_id=?
    """, (rid, lid)).fetchone()

@bp.route("/landlord/rooms/<int:rid>/photos", methods=["GET","POST"])
def room_photos(rid: int):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()

    conn = get_db()
    room = _owned_room_or_none(conn, rid, lid)
    if not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    try:
        assert_room_images_schema(conn)
    except Exception as e:
        conn.close()
        flash(f"Room photos are unavailable: {e}", "error")
        return render_template("photos_room.html", room=room, images=[], max_images=MAX_FILES_PER_ROOM)

    if request.method == "POST":
        files = request.files.getlist("photos")
        files = [f for f in files if getattr(f, "filename", "").strip()]
        if not files:
            imgs = select_room_images(conn, rid)
            conn.close()
            flash("Please choose at least one photo to upload.", "error")
            return render_template("photos_room.html", room=room, images=imgs, max_images=MAX_FILES_PER_ROOM)

        existing = len(select_room_images(conn, rid))
        remaining = max(0, MAX_FILES_PER_ROOM - existing)
        if remaining <= 0:
            conn.close()
            flash(f"Room already has {MAX_FILES_PER_ROOM} photos.", "error")
            return redirect(url_for("landlord.room_photos", rid=rid))

        to_process = files[:remaining]
        successes, errors = 0, []
        for f in to_process:
            ok, msg = accept_upload_room(conn, rid, f, enforce_limit=False)
            if ok: successes += 1
            else: errors.append(f"{getattr(f, 'filename','file')}: {msg}")

        try:
            if successes: conn.commit()
            else: conn.rollback()
        except Exception:
            flash("Could not finalize the upload.", "error")
            conn.close()
            return redirect(url_for("landlord.room_photos", rid=rid))

        parts = []
        if successes: parts.append(f"Uploaded {successes} file{'s' if successes!=1 else ''}.")
        if errors: parts.append(f"Skipped {len(errors)} due to errors.")
        skipped = len(files) - len(to_process)
        if skipped>0: parts.append(f"{skipped} not processed (room limit {MAX_FILES_PER_ROOM}).")

        flash(" ".join(parts) if parts else "Done.", "ok" if successes else "error")
        for e in errors: flash(e, "error")

        conn.close()
        return redirect(url_for("landlord.room_photos", rid=rid))

    # GET
    imgs = select_room_images(conn, rid)
    conn.close()
    return render_template("photos_room.html", room=room, images=imgs, max_images=MAX_FILES_PER_ROOM)

@bp.route("/landlord/rooms/<int:rid>/photos/<int:img_id>/primary", methods=["POST"])
def room_photos_primary(rid: int, img_id: int):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    room = _owned_room_or_none(conn, rid, lid)
    if not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

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

    return redirect(url_for("landlord.room_photos", rid=rid))

@bp.route("/landlord/rooms/<int:rid>/photos/<int:img_id>/delete", methods=["POST"])
def room_photos_delete(rid: int, img_id: int):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    room = _owned_room_or_none(conn, rid, lid)
    if not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    try:
        assert_room_images_schema(conn)
        fname = delete_room_image(conn, rid, img_id)
        if not fname:
            conn.rollback()
            conn.close()
            flash("Photo not found.", "error")
            return redirect(url_for("landlord.room_photos", rid=rid))

        conn.commit()
        conn.close()

        # Best-effort disk cleanup after DB success
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

    return redirect(url_for("landlord.room_photos", rid=rid))
