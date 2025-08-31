# landlord/houses.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt
from db import get_db
from utils import (
    current_landlord_id, require_landlord, get_active_cities_safe,
    owned_house_or_none
)
from . import bp
from . import house_form, house_repo


@bp.route("/landlord/houses")
def landlord_houses():
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()
    conn = get_db()
    prof = conn.execute(
        "SELECT is_verified FROM landlord_profiles WHERE landlord_id=?", (lid,)
    ).fetchone()
    rows = conn.execute(
        "SELECT * FROM houses WHERE landlord_id=? ORDER BY created_at DESC", (lid,)
    ).fetchall()
    conn.close()
    is_verified = int(prof["is_verified"]) if (prof and "is_verified" in prof.keys()) else 0
    return render_template("houses_list.html", houses=rows, is_verified=is_verified)


@bp.route("/landlord/houses/new", methods=["GET", "POST"])
def house_new():
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()
    cities = get_active_cities_safe()

    conn = get_db()
    default_listing_type = house_form.get_default_listing_type(conn, lid)

    if request.method == "POST":
        payload, errors = house_form.parse_house_form(request.form, mode="new", default_listing_type=default_listing_type)

        if errors:
            for e in errors:
                flash(e, "error")
            conn.close()
            return render_template(
                "house_form.html",
                cities=cities,
                form=request.form,
                mode="new",
                default_listing_type=default_listing_type,
            )

        payload["created_at"] = dt.utcnow().isoformat()
        house_repo.insert_house(conn, lid, payload)
        conn.close()
        flash("House added.", "ok")
        return redirect(url_for("landlord.landlord_houses"))

    conn.close()
    return render_template("house_form.html", cities=cities, form={}, mode="new", default_listing_type=default_listing_type)


@bp.route("/landlord/houses/<int:hid>/edit", methods=["GET", "POST"])
def house_edit(hid):
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()
    cities = get_active_cities_safe()
    conn = get_db()
    house_row = owned_house_or_none(conn, hid, lid)
    if not house_row:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    house = dict(house_row)
    default_listing_type = house_form.get_default_listing_type(conn, lid, existing=house)

    if request.method == "POST":
        payload, errors = house_form.parse_house_form(request.form, mode="edit", default_listing_type=default_listing_type)

        if errors:
            for e in errors:
                flash(e, "error")
            conn.close()
            return render_template(
                "house_form.html",
                cities=cities,
                form=request.form,
                mode="edit",
                house=house,
                default_listing_type=default_listing_type,
            )

        house_repo.update_house(conn, lid, hid, payload)
        conn.close()
        flash("House updated.", "ok")
        return redirect(url_for("landlord.landlord_houses"))

    # GET
    form = dict(house)
    form.setdefault("bills_option", house.get("bills_option") or ("yes" if (house.get("bills_included") == 1) else "no"))
    conn.close()
    return render_template(
        "house_form.html",
        cities=cities,
        form=form,
        mode="edit",
        house=house,
        default_listing_type=default_listing_type,
    )


@bp.route("/landlord/houses/<int:hid>/delete", methods=["POST"])
def house_delete(hid):
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()
    conn = get_db()
    conn.execute(
        "DELETE FROM rooms WHERE house_id=(SELECT id FROM houses WHERE id=? AND landlord_id=?)",
        (hid, lid),
    )
    conn.execute("DELETE FROM houses WHERE id=? AND landlord_id=?", (hid, lid))
    conn.commit()
    conn.close()
    flash("House deleted.", "ok")
    return redirect(url_for("landlord.landlord_houses"))
