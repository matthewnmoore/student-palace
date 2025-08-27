from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime as dt
from db import get_db
from utils import (
    current_landlord_id, require_landlord, get_active_cities_safe,
    validate_city_active, clean_bool, valid_choice, owned_house_or_none
)

landlord_bp = Blueprint("landlord", __name__, url_prefix="")

@landlord_bp.route("/dashboard")
def dashboard():
    lid = current_landlord_id()
    if not lid:
        return render_template("dashboard.html", landlord=None, profile=None)
    conn = get_db()
    landlord = conn.execute("SELECT id,email,created_at FROM landlords WHERE id=?", (lid,)).fetchone()
    profile = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
    houses = conn.execute("SELECT * FROM houses WHERE landlord_id=? ORDER BY created_at DESC", (lid,)).fetchall()
    conn.close()
    return render_template("dashboard.html", landlord=landlord, profile=profile, houses=houses)

@landlord_bp.route("/landlord/profile", methods=["GET","POST"])
def landlord_profile():
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    prof = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
    if not prof:
        conn.execute("INSERT INTO landlord_profiles(landlord_id, display_name) VALUES (?,?)", (lid, ""))
        conn.commit()
        prof = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()

    if request.method == "POST":
        try:
            from utils import slugify
            display_name = (request.form.get("display_name") or "").strip()
            phone = (request.form.get("phone") or "").strip()
            website = (request.form.get("website") or "").strip()
            bio = (request.form.get("bio") or "").strip()
            slug = prof["public_slug"]
            if not slug and display_name:
                base = slugify(display_name)
                candidate = base
                i = 2
                while conn.execute("SELECT 1 FROM landlord_profiles WHERE public_slug=?", (candidate,)).fetchone():
                    candidate = f"{base}-{i}"
                    i += 1
                slug = candidate
            conn.execute("""
                UPDATE landlord_profiles
                SET display_name=?, phone=?, website=?, bio=?, public_slug=COALESCE(?, public_slug)
                WHERE landlord_id=?
            """, (display_name, phone, website, bio, slug, lid))
            conn.commit()
            prof = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
            conn.close()
            flash("Profile saved.", "ok")
            return redirect(url_for("landlord.landlord_profile"))
        except Exception as e:
            conn.close()
            print("[ERROR] landlord_profile POST:", e)
            flash("Could not save profile.", "error")
            return redirect(url_for("landlord.landlord_profile"))

    conn.close()
    return render_template("landlord_profile_edit.html", profile=prof)

# Public profile views
@landlord_bp.route("/l/<slug>")
def landlord_public_by_slug(slug):
    conn = get_db()
    prof = conn.execute("SELECT * FROM landlord_profiles WHERE public_slug=?", (slug,)).fetchone()
    if not prof:
        conn.close()
        return render_template("landlord_profile_public.html", profile=None), 404
    conn.execute("UPDATE landlord_profiles SET profile_views=profile_views+1 WHERE landlord_id=?", (prof["landlord_id"],))
    conn.commit()
    ll = conn.execute("SELECT email FROM landlords WHERE id=?", (prof["landlord_id"],)).fetchone()
    conn.close()
    return render_template("landlord_profile_public.html", profile=prof, contact_email=ll["email"] if ll else "")

@landlord_bp.route("/l/id/<int:lid>")
def landlord_public_by_id(lid):
    conn = get_db()
    prof = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
    if not prof:
        conn.close()
        return render_template("landlord_profile_public.html", profile=None), 404
    conn.execute("UPDATE landlord_profiles SET profile_views=profile_views+1 WHERE landlord_id=?", (lid,))
    conn.commit()
    ll = conn.execute("SELECT email FROM landlords WHERE id=?", (lid,)).fetchone()
    conn.close()
    return render_template("landlord_profile_public.html", profile=prof, contact_email=ll["email"] if ll else "")

# Houses (list/new/edit/delete)
@landlord_bp.route("/landlord/houses")
def landlord_houses():
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    rows = conn.execute("SELECT * FROM houses WHERE landlord_id=? ORDER BY created_at DESC", (lid,)).fetchall()
    conn.close()
    return render_template("houses_list.html", houses=rows)

@landlord_bp.route("/landlord/houses/new", methods=["GET","POST"])
def house_new():
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    cities = get_active_cities_safe()

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        city = (request.form.get("city") or "").strip()
        address = (request.form.get("address") or "").strip()
        letting_type = (request.form.get("letting_type") or "").strip()
        gender_pref = (request.form.get("gender_preference") or "").strip()
        bills_included = clean_bool("bills_included")
        shared_bathrooms = int(request.form.get("shared_bathrooms") or 0)
        bedrooms_total = int(request.form.get("bedrooms_total") or 0)

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
        if errors:
            for e in errors: flash(e, "error")
            return render_template("house_form.html", cities=cities, form=request.form, mode="new")

        conn = get_db()
        conn.execute("""
          INSERT INTO houses(
            landlord_id,title,city,address,letting_type,bedrooms_total,gender_preference,bills_included,
            shared_bathrooms,off_street_parking,local_parking,cctv,video_door_entry,bike_storage,cleaning_service,
            wifi,wired_internet,common_area_tv,created_at
          ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            lid, title, city, address, letting_type, bedrooms_total, gender_pref, bills_included,
            shared_bathrooms, off_street_parking, local_parking, cctv, video_door_entry, bike_storage,
            cleaning_service, wifi, wired_internet, common_area_tv, dt.utcnow().isoformat()
        ))
        conn.commit()
        conn.close()
        flash("House added.", "ok")
        return redirect(url_for("landlord.landlord_houses"))

    return render_template("house_form.html", cities=cities, form={}, mode="new")

@landlord_bp.route("/landlord/houses/<int:hid>/edit", methods=["GET","POST"])
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

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        city = (request.form.get("city") or "").strip()
        address = (request.form.get("address") or "").strip()
        letting_type = (request.form.get("letting_type") or "").strip()
        gender_pref = (request.form.get("gender_preference") or "").strip()
        bills_included = clean_bool("bills_included")
        shared_bathrooms = int(request.form.get("shared_bathrooms") or 0)
        bedrooms_total = int(request.form.get("bedrooms_total") or 0)

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
        if errors:
            for e in errors: flash(e, "error")
            conn.close()
            return render_template("house_form.html", cities=cities, form=request.form, mode="edit", house=house)

        conn.execute("""
          UPDATE houses SET
            title=?, city=?, address=?, letting_type=?, bedrooms_total=?, gender_preference=?, bills_included=?,
            shared_bathrooms=?, off_street_parking=?, local_parking=?, cctv=?, video_door_entry=?, bike_storage=?,
            cleaning_service=?, wifi=?, wired_internet=?, common_area_tv=?
          WHERE id=? AND landlord_id=?
        """, (
            title, city, address, letting_type, bedrooms_total, gender_pref, bills_included,
            shared_bathrooms, off_street_parking, local_parking, cctv, video_door_entry, bike_storage,
            cleaning_service, wifi, wired_internet, common_area_tv, hid, lid
        ))
        conn.commit()
        conn.close()
        flash("House updated.", "ok")
        return redirect(url_for("landlord.landlord_houses"))

    form = dict(house)
    conn.close()
    return render_template("house_form.html", cities=cities, form=form, mode="edit", house=house)

@landlord_bp.route("/landlord/houses/<int:hid>/delete", methods=["POST"])
def house_delete(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    # Safety: also delete rooms if FK pragma off
    conn.execute("DELETE FROM rooms WHERE house_id=(SELECT id FROM houses WHERE id=? AND landlord_id=?)", (hid, lid))
    conn.execute("DELETE FROM houses WHERE id=? AND landlord_id=?", (hid, lid))
    conn.commit()
    conn.close()
    flash("House deleted.", "ok")
    return redirect(url_for("landlord.landlord_houses"))

# Rooms CRUD
def _room_form_values(request):
    name = (request.form.get("name") or "").strip()
    from utils import clean_bool
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

@landlord_bp.route("/landlord/houses/<int:hid>/rooms")
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
    conn.close()
    return render_template("rooms_list.html", house=house, rooms=rows)

@landlord_bp.route("/landlord/houses/<int:hid>/rooms/new", methods=["GET","POST"])
def room_new(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        return redirect(url_for("landlord.landlord_houses"))

    if request.method == "POST":
        vals, errors = _room_form_values(request)
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

@landlord_bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/edit", methods=["GET","POST"])
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
        vals, errors = _room_form_values(request)
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

@landlord_bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/delete", methods=["POST"])
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
