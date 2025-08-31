# landlord/houses.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt

from db import get_db
from utils import (
    current_landlord_id,
    require_landlord,
    get_active_cities_safe,
    validate_city_active,
    clean_bool,
    valid_choice,
    owned_house_or_none,
)
from . import bp


# ---------- Helpers ----------

BILLS_UTIL_FIELDS = (
    "bills_util_gas",
    "bills_util_electric",
    "bills_util_water",
    "bills_util_broadband",
    "bills_util_tv",
)

AMENITY_CHECKBOX_FIELDS = (
    # kitchen / appliances
    "washing_machine",
    "tumble_dryer",
    "dishwasher",
    "cooker",
    "microwave",
    "coffee_maker",
    # comfort / connectivity
    "central_heating",
    "air_conditioning",  # maps to DB col air_con
    "vacuum",
    "wifi",
    "wired_internet",
    "common_area_tv",
    # security / access
    "cctv",
    "video_door_entry",
    "fob_entry",
    # parking / outdoors
    "off_street_parking",
    "local_parking",
    "garden",
    "roof_terrace",
    "bike_storage",
    # extras
    "games_room",
    "cinema_room",
)


def _read_bills_from_form():
    """
    Read bills_option and util flags from the POSTed form, enforcing the rules:
      - yes  -> all utils = 1
      - no   -> all utils = 0
      - some -> use checkboxes as posted
    Returns: (bills_option:str, bills_included_legacy:int, util_flags:dict[str,int])
    """
    opt = (request.form.get("bills_included") or "no").strip().lower()
    if opt not in ("yes", "no", "some"):
        opt = "no"

    # legacy boolean kept for backwards compatibility / older templates
    bills_included_legacy = 1 if opt == "yes" else 0

    # default util states from form (used when opt == "some")
    utils_from_form = {name: (1 if clean_bool(name) else 0) for name in BILLS_UTIL_FIELDS}

    if opt == "yes":
        util_flags = {name: 1 for name in BILLS_UTIL_FIELDS}
    elif opt == "no":
        util_flags = {name: 0 for name in BILLS_UTIL_FIELDS}
    else:
        util_flags = utils_from_form  # "some"

    return opt, bills_included_legacy, util_flags


def _read_amenities_from_form():
    """
    Read all amenity checkboxes as ints (0/1).
    Note: 'air_conditioning' (form name) maps to DB column 'air_con'.
    """
    vals = {name: (1 if clean_bool(name) else 0) for name in AMENITY_CHECKBOX_FIELDS}
    return vals


# ---------- Routes ----------

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
    prof = conn.execute(
        "SELECT role FROM landlord_profiles WHERE landlord_id=?", (lid,)
    ).fetchone()
    default_listing_type = (
        prof["role"] if prof and prof["role"] in ("owner", "agent") else "owner"
    )

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        city = (request.form.get("city") or "").strip()
        address = (request.form.get("address") or "").strip()
        letting_type = (request.form.get("letting_type") or "").strip()
        gender_pref = (request.form.get("gender_preference") or "").strip()

        bills_option, bills_included_legacy, util_flags = _read_bills_from_form()

        shared_bathrooms = int(request.form.get("shared_bathrooms") or 0)
        bedrooms_total = int(request.form.get("bedrooms_total") or 0)
        listing_type = (request.form.get("listing_type") or default_listing_type or "owner").strip()

        amenities = _read_amenities_from_form()
        cleaning_service = (request.form.get("cleaning_service") or "none").strip()

        # Validation
        errors = []
        if not title:
            errors.append("Title is required.")
        if not address:
            errors.append("Address is required.")
        if bedrooms_total < 1:
            errors.append("Bedrooms must be at least 1.")
        if not validate_city_active(city):
            errors.append("Please choose a valid active city.")
        if not valid_choice(letting_type, ("whole", "share")):
            errors.append("Invalid letting type.")
        if not valid_choice(gender_pref, ("Male", "Female", "Mixed", "Either")):
            errors.append("Invalid gender preference.")
        if not valid_choice(cleaning_service, ("none", "weekly", "fortnightly", "monthly")):
            errors.append("Invalid cleaning service value.")
        if not valid_choice(listing_type, ("owner", "agent")):
            errors.append("Invalid listing type.")

        if errors:
            for e in errors:
                flash(e, "error")
            conn.close()
            f = dict(request.form)
            f["listing_type"] = listing_type
            f["bills_option"] = bills_option
            # ensure util checkboxes survive re-render
            for k, v in util_flags.items():
                f[k] = "1" if v else "0"
            return render_template(
                "house_form.html",
                cities=cities,
                form=f,
                mode="new",
                default_listing_type=default_listing_type,
            )

        # Insert
        conn.execute(
            """
          INSERT INTO houses(
            landlord_id,title,city,address,letting_type,bedrooms_total,gender_preference,
            bills_included, bills_option,
            bills_util_gas, bills_util_electric, bills_util_water, bills_util_broadband, bills_util_tv,
            shared_bathrooms,
            washing_machine,tumble_dryer,dishwasher,cooker,microwave,coffee_maker,
            central_heating,air_con,vacuum,
            wifi,wired_internet,common_area_tv,
            cctv,video_door_entry,fob_entry,
            off_street_parking,local_parking,garden,roof_terrace,bike_storage,games_room,cinema_room,
            cleaning_service, listing_type, created_at
          ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                lid,
                title,
                city,
                address,
                letting_type,
                bedrooms_total,
                gender_pref,
                bills_included_legacy,
                bills_option,
                util_flags["bills_util_gas"],
                util_flags["bills_util_electric"],
                util_flags["bills_util_water"],
                util_flags["bills_util_broadband"],
                util_flags["bills_util_tv"],
                shared_bathrooms,
                amenities["washing_machine"],
                amenities["tumble_dryer"],
                amenities["dishwasher"],
                amenities["cooker"],
                amenities["microwave"],
                amenities["coffee_maker"],
                amenities["central_heating"],
                amenities["air_conditioning"],  # will go into air_con
                amenities["vacuum"],
                amenities["wifi"],
                amenities["wired_internet"],
                amenities["common_area_tv"],
                amenities["cctv"],
                amenities["video_door_entry"],
                amenities["fob_entry"],
                amenities["off_street_parking"],
                amenities["local_parking"],
                amenities["garden"],
                amenities["roof_terrace"],
                amenities["bike_storage"],
                amenities["games_room"],
                amenities["cinema_room"],
                cleaning_service,
                listing_type,
                dt.utcnow().isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        flash("House added.", "ok")
        return redirect(url_for("landlord.landlord_houses"))

    conn.close()
    return render_template(
        "house_form.html",
        cities=cities,
        form={},
        mode="new",
        default_listing_type=default_listing_type,
    )


@bp.route("/landlord/houses/<int:hid>/edit", methods=["GET", "POST"])
def house_edit(hid):
    r = require_landlord()
    if r:
        return r
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
    default_listing_type = (
        house["listing_type"]
        if "listing_type" in house.keys() and house["listing_type"]
        else (prof["role"] if prof and prof["role"] in ("owner", "agent") else "owner")
    )

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        city = (request.form.get("city") or "").strip()
        address = (request.form.get("address") or "").strip()
        letting_type = (request.form.get("letting_type") or "").strip()
        gender_pref = (request.form.get("gender_preference") or "").strip()

        bills_option, bills_included_legacy, util_flags = _read_bills_from_form()

        shared_bathrooms = int(request.form.get("shared_bathrooms") or 0)
        bedrooms_total = int(request.form.get("bedrooms_total") or 0)
        listing_type = (request.form.get("listing_type") or default_listing_type or "owner").strip()

        amenities = _read_amenities_from_form()
        cleaning_service = (request.form.get("cleaning_service") or "none").strip()

        # Validation
        errors = []
        if not title:
            errors.append("Title is required.")
        if not address:
            errors.append("Address is required.")
        if bedrooms_total < 1:
            errors.append("Bedrooms must be at least 1.")
        if not validate_city_active(city):
            errors.append("Please choose a valid active city.")
        if not valid_choice(letting_type, ("whole", "share")):
            errors.append("Invalid letting type.")
        if not valid_choice(gender_pref, ("Male", "Female", "Mixed", "Either")):
            errors.append("Invalid gender preference.")
        if not valid_choice(cleaning_service, ("none", "weekly", "fortnightly", "monthly")):
            errors.append("Invalid cleaning service value.")
        if not valid_choice(listing_type, ("owner", "agent")):
            errors.append("Invalid listing type.")

        if errors:
            for e in errors:
                flash(e, "error")
            conn.close()
            f = dict(request.form)
            f["listing_type"] = listing_type
            f["bills_option"] = bills_option
            for k, v in util_flags.items():
                f[k] = "1" if v else "0"
            return render_template(
                "house_form.html",
                cities=cities,
                form=f,
                mode="edit",
                house=house,
                default_listing_type=default_listing_type,
            )

        # Update
        conn.execute(
            """
          UPDATE houses SET
            title=?, city=?, address=?, letting_type=?, bedrooms_total=?, gender_preference=?,
            bills_included=?, bills_option=?,
            bills_util_gas=?, bills_util_electric=?, bills_util_water=?, bills_util_broadband=?, bills_util_tv=?,
            shared_bathrooms=?,
            washing_machine=?,tumble_dryer=?,dishwasher=?,cooker=?,microwave=?,coffee_maker=?,
            central_heating=?,air_con=?,vacuum=?,
            wifi=?,wired_internet=?,common_area_tv=?,
            cctv=?,video_door_entry=?,fob_entry=?,
            off_street_parking=?,local_parking=?,garden=?,roof_terrace=?,bike_storage=?,games_room=?,cinema_room=?,
            cleaning_service=?, listing_type=?
          WHERE id=? AND landlord_id=?
        """,
            (
                title,
                city,
                address,
                letting_type,
                bedrooms_total,
                gender_pref,
                bills_included_legacy,
                bills_option,
                util_flags["bills_util_gas"],
                util_flags["bills_util_electric"],
                util_flags["bills_util_water"],
                util_flags["bills_util_broadband"],
                util_flags["bills_util_tv"],
                shared_bathrooms,
                amenities["washing_machine"],
                amenities["tumble_dryer"],
                amenities["dishwasher"],
                amenities["cooker"],
                amenities["microwave"],
                amenities["coffee_maker"],
                amenities["central_heating"],
                amenities["air_conditioning"],  # -> air_con
                amenities["vacuum"],
                amenities["wifi"],
                amenities["wired_internet"],
                amenities["common_area_tv"],
                amenities["cctv"],
                amenities["video_door_entry"],
                amenities["fob_entry"],
                amenities["off_street_parking"],
                amenities["local_parking"],
                amenities["garden"],
                amenities["roof_terrace"],
                amenities["bike_storage"],
                amenities["games_room"],
                amenities["cinema_room"],
                cleaning_service,
                listing_type,
                hid,
                lid,
            ),
        )
        conn.commit()
        conn.close()
        flash("House updated.", "ok")
        return redirect(url_for("landlord.landlord_houses"))

    # GET (edit)
    form = dict(house)
    # Ensure edit form has a visible bills_option (fallback to legacy)
    form.setdefault(
        "bills_option",
        house.get("bills_option") or ("yes" if house.get("bills_included") == 1 else "no"),
    )
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
