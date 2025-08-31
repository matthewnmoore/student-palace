from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt
from db import get_db
from utils import (
    current_landlord_id, require_landlord, get_active_cities_safe,
    owned_house_or_none, validate_city_active, clean_bool, valid_choice
)
from . import bp
from . import house_form, house_repo


# -----------------------------
# Address normalization helpers
# -----------------------------
def _title_case_wordish(s: str) -> str:
    """
    Light title-casing suitable for UK addresses:
    - Lowercases everything, then uppercases word initials
    - Also title-cases parts after hyphens and apostrophes (O'Connor, High-Street)
    NOTE: This is intentionally simple and won't perfectly handle all name rules.
    """
    s = (s or "").strip()
    if not s:
        return s
    s = s.lower()

    out = []
    capitalize_next = True
    for ch in s:
        if capitalize_next and ch.isalpha():
            out.append(ch.upper())
            capitalize_next = False
        else:
            out.append(ch)
        if ch in (" ", "-", "’", "'"):
            capitalize_next = True
    return "".join(out)


def _normalize_postcode(pc: str) -> str:
    pc = (pc or "").strip().upper()
    if not pc:
        return ""
    # Insert a single space before the last 3 characters if missing and length allows
    if " " not in pc and len(pc) > 3:
        pc = pc[:-3] + " " + pc[-3:]
    return pc


def _compose_address_from_parts(form) -> str:
    """
    Backend safety net: build the one-line address from individual fields.
    We title-case the non-postcode components and uppercase the postcode.
    """
    f = lambda k: (form.get(k) or "").strip()
    flat_number   = _title_case_wordish(f("flat_number"))
    house_name    = _title_case_wordish(f("house_name"))
    house_number  = _title_case_wordish(f("house_number"))
    street_name   = _title_case_wordish(f("street_name"))
    address_extra = _title_case_wordish(f("address_extra"))
    city          = _title_case_wordish(f("city"))
    postcode      = _normalize_postcode(f("postcode"))

    line1 = " ".join(x for x in [flat_number, (house_name or house_number), street_name] if x)
    line2 = address_extra
    line3 = city

    parts = [line1, line2, line3]
    non_empty = [p for p in parts if p and p.replace(",", "").strip()]

    composed = ", ".join(non_empty + ([postcode] if postcode else []))
    return composed.strip()


def _normalize_full_address(s: str) -> str:
    """
    Normalize a pre-built one-line address (e.g., from hidden field).
    Title-case non-postcode parts, uppercase/space the final postcode if present.
    """
    s = (s or "").strip()
    if not s:
        return ""
    bits = [b.strip() for b in s.split(",") if b.strip()]
    if not bits:
        return ""

    # Try to treat the last bit as postcode
    if len(bits) >= 1:
        last = _normalize_postcode(bits[-1])
        # Title-case all prior bits
        prior = [_title_case_wordish(b) for b in bits[:-1]]
        return ", ".join(prior + ([last] if last else [])) if last else ", ".join([_title_case_wordish(b) for b in bits])
    return ", ".join([_title_case_wordish(b) for b in bits])


# -------------------------------------------------------
# Parser wrapper (uses house_form.parse_house_form if set)
# -------------------------------------------------------
def _parse_or_delegate(form, mode: str, default_listing_type: str, existing_address: str | None = None):
    """
    Use house_form.parse_house_form if available.
    Fallback to an inline parser so we never 500.
    Returns: (payload: dict, errors: list[str])
    """
    if hasattr(house_form, "parse_house_form"):
        return house_form.parse_house_form(form, mode=mode, default_listing_type=default_listing_type)

    # ---- Fallback parser ----
    fget = lambda k, default="": (form.get(k) or default).strip()

    title = fget("title")
    city = fget("city")
    letting_type = fget("letting_type")
    gender_pref = fget("gender_preference")

    # Always normalize the address we save:
    # 1) Prefer the hidden preview address if present (normalize it)
    # 2) Else compose from parts (normalized)
    # 3) Edit safety net: if still empty but we have an existing address, keep it
    address_hidden = fget("address")
    address = _normalize_full_address(address_hidden) if address_hidden else _compose_address_from_parts(form)
    if mode == "edit" and (not address) and existing_address:
        address = _normalize_full_address(existing_address)

    # Bills dropdown -> houses.bills_option (+ legacy flag)
    bills_option = (form.get("bills_included") or "no").strip().lower()
    if bills_option not in ("yes", "no", "some"):
        bills_option = "no"
    bills_included_legacy = 1 if bills_option == "yes" else 0

    # Detailed utilities
    if bills_option == "yes":
        bills_util = dict(
            bills_util_gas=1, bills_util_electric=1, bills_util_water=1,
            bills_util_broadband=1, bills_util_tv=1
        )
    elif bills_option == "some":
        bills_util = dict(
            bills_util_gas=clean_bool("bills_util_gas"),
            bills_util_electric=clean_bool("bills_util_electric"),
            bills_util_water=clean_bool("bills_util_water"),
            bills_util_broadband=clean_bool("bills_util_broadband"),
            bills_util_tv=clean_bool("bills_util_tv"),
        )
    else:
        bills_util = dict(
            bills_util_gas=0, bills_util_electric=0, bills_util_water=0,
            bills_util_broadband=0, bills_util_tv=0
        )

    shared_bathrooms = int(form.get("shared_bathrooms") or 0)
    bedrooms_total = int(form.get("bedrooms_total") or 0)
    listing_type = (form.get("listing_type") or default_listing_type or "owner").strip()

    # EPC rating (optional A–G). Store empty string if not valid/selected.
    epc_rating_raw = (form.get("epc_rating") or "").strip().upper()
    epc_rating = epc_rating_raw if epc_rating_raw in ("A", "B", "C", "D", "E", "F", "G") else ""

    # Payload (address already normalized)
    payload = {
        "title": title,
        "city": _title_case_wordish(city),  # keep city nicely cased
        "address": address,
        "letting_type": letting_type,
        "bedrooms_total": bedrooms_total,
        "gender_preference": gender_pref,
        "bills_included": bills_included_legacy,
        "bills_option": bills_option,
        "shared_bathrooms": shared_bathrooms,
        "washing_machine": clean_bool("washing_machine"),
        "tumble_dryer": clean_bool("tumble_dryer"),
        "dishwasher": clean_bool("dishwasher"),
        "cooker": clean_bool("cooker"),
        "microwave": clean_bool("microwave"),
        "coffee_maker": clean_bool("coffee_maker"),
        "central_heating": clean_bool("central_heating"),
        "air_con": clean_bool("air_conditioning"),
        "vacuum": clean_bool("vacuum"),
        "wifi": clean_bool("wifi"),
        "wired_internet": clean_bool("wired_internet"),
        "common_area_tv": clean_bool("common_area_tv"),
        "cctv": clean_bool("cctv"),
        "video_door_entry": clean_bool("video_door_entry"),
        "fob_entry": clean_bool("fob_entry"),
        "off_street_parking": clean_bool("off_street_parking"),
        "local_parking": clean_bool("local_parking"),
        "garden": clean_bool("garden"),
        "roof_terrace": clean_bool("roof_terrace"),
        "bike_storage": clean_bool("bike_storage"),
        "games_room": clean_bool("games_room"),
        "cinema_room": clean_bool("cinema_room"),
        "cleaning_service": (form.get("cleaning_service") or "none").strip(),
        "listing_type": listing_type,
        "epc_rating": epc_rating,
    }
    payload.update(bills_util)

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
    if not valid_choice(payload["cleaning_service"], ("none", "weekly", "fortnightly", "monthly")):
        errors.append("Invalid cleaning service value.")
    if not valid_choice(listing_type, ("owner", "agent")):
        errors.append("Invalid listing type.")
    if epc_rating_raw and epc_rating == "":
        errors.append("Invalid EPC rating (choose A, B, C, D, E, F or G).")

    return payload, errors
    # ---- End fallback ----


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
        payload, errors = _parse_or_delegate(request.form, mode="new", default_listing_type=default_listing_type)

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
        payload, errors = _parse_or_delegate(
            request.form, mode="edit",
            default_listing_type=default_listing_type,
            existing_address=house.get("address")
        )

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
