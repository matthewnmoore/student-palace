from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt
from db import get_db
from utils import (
    current_landlord_id, require_landlord, get_active_cities_safe,
    validate_city_active, clean_bool, valid_choice, owned_house_or_none
)
from . import bp

@bp.route("/landlord/houses")
def landlord_houses():
    r = require_landlord()
    if r: return r
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
    return render_template(
        "houses_list.html",
        houses=rows,
        is_verified=is_verified
    )

@bp.route("/landlord/houses/new", methods=["GET","POST"])
def house_new():
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    cities = get_active_cities_safe()

    conn = get_db()
    prof = conn.execute(
        "SELECT role FROM landlord_profiles WHERE landlord_id=?", (lid,)
    ).fetchone()
    default_listing_type = (prof["role"] if prof and prof["role"] in ("owner","agent") else "owner")

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        city = (request.form.get("city") or "").strip()
        address = (request.form.get("address") or "").strip()
        letting_type = (request.form.get("letting_type") or "").strip()
        gender_pref = (request.form.get("gender_preference") or "").strip()
        bills_included = clean_bool("bills_included")
        shared_bathrooms = int(request.form.get("shared_bathrooms") or 0)
        bedrooms_total = int(request.form.get("bedrooms_total") or 0)
        listing_type = (request.form.get("listing_type") or default_listing_type or "owner").strip()

        off_street_parking = clean_bool("off_street_parking")
        local_parking = clean_bool("local_parking")
        cctv = clean_bool("cctv")
        video_door_entry = clean_bool("video_door_entry")
        bike_storage = clean_bool("bike_storage")
        cleaning_service = (request.form.get("cleaning_service") or "none").strip()
        wifi = 1 if request.form.get("wifi") is None else clean_bool("wifi")
        wired_internet = clean_bool("wired_internet")
        common_area_tv = clean_bool("common_area_tv")

        errors = []
        if not title: errors.append("Title is required.")
        if not address: errors.append("Address is required.")
        if bedrooms_total < 1: errors.append("Bedrooms must be at least 1.")
        if not validate_city_active(city): errors.append("Please choose a valid active city.")
        if not valid_choice(letting_type, ("whole","share")): errors.append("Invalid letting type.")
        if not valid_choice(gender_pref, ("Male","Female","Mixed","Either")): errors.append("Invalid gender preference.")
        if not valid_choice(cleaning_service, ("none","weekly","fortnightly","monthly")): errors.append("Invalid cleaning service value.")
        if not valid_choice(listing_type, ("owner","agent")): errors.append("Invalid listing type.")
        if errors:
            for e in errors: flash(e, "error")
            conn.close()
            f = dict(request.form)
            f["listing_type"] = listing_type
            return render_template("house_form.html", cities=cities, form=f, mode="new", default_listing_type=default_listing_type)

        conn.execute("""
          INSERT INTO houses(
            landlord_id,title,city,address,letting_type,bedrooms_total,gender_preference,bills_included,
            shared_bathrooms,off_street_parking,local_parking,cctv,video_door_entry,bike_storage,cleaning_service,
            wifi,wired_internet,common_area_tv,listing_type,created_at
          ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            lid, title, city, address, letting_type, bedrooms_total, gender_pref, bills_included,
            shared_bathrooms, off_street_parking, local_parking, cctv, video_door_entry, bike_storage,
            cleaning_service, wifi, wired_internet, common_area_tv, listing_type, dt.utcnow().isoformat()
        ))
        conn.commit()
        conn.close()
        flash("House added.", "ok")
        return redirect(url_for("landlord.landlord_houses"))

    conn.close()
    return render_template("house_form.html", cities=cities, form={}, mode="new", default_listing_type=default_listing_type)

@bp.route("/landlord/houses/<int:hid>/edit", methods=["GET","POST"])
def house_edit(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    cities = get_active_cities_safe()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    prof = conn.execute(
        "SELECT role FROM landlord_profiles WHERE landlord_id=?", (lid,)
    ).fetchone()
    default_listing_type = house["listing_type"] if "listing_type" in house.keys() and house["listing_type"] else (
        prof["role"] if prof and prof["role"] in ("owner","agent") else "owner"
    )

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        city = (request.form.get("city") or "").strip()
        address = (request.form.get("address") or "").strip()
        letting_type = (request.form.get("letting_type") or "").strip()
        gender_pref = (request.form.get("gender_preference") or "").strip()
        bills_included = clean_bool("bills_included")
        shared_bathrooms = int(request.form.get("shared_bathrooms") or 0)
        bedrooms_total = int(request.form.get("bedrooms_total") or 0)
        listing_type = (request.form.get("listing_type") or default_listing_type or "owner").strip()

        off_street_parking = clean_bool("off_street_parking")
        local_parking = clean_bool("local_parking")
        cctv = clean_bool("cctv")
        video_door_entry = clean_bool("video_door_entry")
        bike_storage = clean_bool("bike_storage")
        cleaning_service = (request.form.get("cleaning_service") or "none").strip()
        wifi = 1 if request.form.get("wifi") is None else clean_bool("wifi")
        wired_internet = clean_bool("wired_internet")
        common_area_tv = clean_bool("common_area_tv")

        errors = []
        if not title: errors.append("Title is required.")
        if not address: errors.append("Address is required.")
        if bedrooms_total < 1: errors.append("Bedrooms must be at least 1.")
        if not validate_city_active(city): errors.append("Please choose a valid active city.")
        if not valid_choice(letting_type, ("whole","share")): errors.append("Invalid letting type.")
        if not valid_choice(gender_pref, ("Male","Female","Mixed","Either")): errors.append("Invalid gender preference.")
        if not valid_choice(cleaning_service, ("none","weekly","fortnightly","monthly")): errors.append("Invalid cleaning service value.")
        if not valid_choice(listing_type, ("owner","agent")): errors.append("Invalid listing type.")
        if errors:
            for e in errors: flash(e, "error")
            conn.close()
            f = dict(request.form)
            f["listing_type"] = listing_type
            return render_template("house_form.html", cities=cities, form=f, mode="edit", house=house, default_listing_type=default_listing_type)

        conn.execute("""
          UPDATE houses SET
            title=?, city=?, address=?, letting_type=?, bedrooms_total=?, gender_preference=?, bills_included=?,
            shared_bathrooms=?, off_street_parking=?, local_parking=?, cctv=?, video_door_entry=?, bike_storage=?,
            cleaning_service=?, wifi=?, wired_internet=?, common_area_tv=?, listing_type=?
          WHERE id=? AND landlord_id=?
        """, (
            title, city, address, letting_type, bedrooms_total, gender_pref, bills_included,
            shared_bathrooms, off_street_parking, local_parking, cctv, video_door_entry, bike_storage,
            cleaning_service, wifi, wired_internet, common_area_tv, listing_type, hid, lid
        ))
        conn.commit()
        conn.close()
        flash("House updated.", "ok")
        return redirect(url_for("landlord.landlord_houses"))

    form = dict(house)
    conn.close()
    return render_template("house_form.html", cities=cities, form=form, mode="edit", house=house, default_listing_type=default_listing_type)

@bp.route("/landlord/houses/<int:hid>/delete", methods=["POST"])
def house_delete(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    conn.execute(
        "DELETE FROM rooms WHERE house_id=(SELECT id FROM houses WHERE id=? AND landlord_id=?)",
        (hid, lid)
    )
    conn.execute("DELETE FROM houses WHERE id=? AND landlord_id=?", (hid, lid))
    conn.commit()
    conn.close()
    flash("House deleted.", "ok")
    return redirect(url_for("landlord.landlord_houses"))
