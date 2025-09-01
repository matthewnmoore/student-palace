from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt
from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none
from .helpers import room_form_values, room_counts
from . import bp

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
