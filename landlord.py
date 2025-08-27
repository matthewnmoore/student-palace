import os
import io
import uuid
from datetime import datetime as dt

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from PIL import Image, ImageDraw, ImageFont

from db import get_db
from utils import (
    current_landlord_id, require_landlord, get_active_cities_safe,
    validate_city_active, clean_bool, valid_choice, owned_house_or_none,
    allowed_image_ext
)
from config import UPLOADS_HOUSES_DIR, HOUSE_IMAGES_MAX, WATERMARK_TEXT, IMAGE_MAX_WIDTH, IMAGE_MAX_HEIGHT, IMAGE_TARGET_BYTES

landlord_bp = Blueprint("landlord", __name__, url_prefix="")

@landlord_bp.route("/dashboard")
def dashboard():
    lid = current_landlord_id()
    if not lid:
        return render_template("dashboard.html", landlord=None, profile=None)

    conn = get_db()
    landlord = conn.execute(
        "SELECT id,email,created_at FROM landlords WHERE id=?", (lid,)
    ).fetchone()
    profile = conn.execute(
        "SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)
    ).fetchone()
    houses = conn.execute(
        "SELECT * FROM houses WHERE landlord_id=? ORDER BY created_at DESC", (lid,)
    ).fetchall()
    conn.close()

    # UK-style "Member since"
    created_at_uk = None
    try:
        created_at_uk = dt.fromisoformat(landlord["created_at"]).strftime("%d %B %Y")
    except Exception:
        created_at_uk = landlord["created_at"]

    # role label
    role_raw = (profile["role"] if profile and "role" in profile.keys() else "owner") or "owner"
    role_label = "Owner" if role_raw == "owner" else "Agent"

    return render_template(
        "dashboard.html",
        landlord=landlord,
        profile=profile,
        houses=houses,
        created_at_uk=created_at_uk,
        role_label=role_label
    )

@landlord_bp.route("/landlord/profile", methods=["GET","POST"])
def landlord_profile():
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    prof = conn.execute(
        "SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)
    ).fetchone()
    if not prof:
        conn.execute(
            "INSERT INTO landlord_profiles(landlord_id, display_name) VALUES (?,?)",
            (lid, "")
        )
        conn.commit()
        prof = conn.execute(
            "SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)
        ).fetchone()

    if request.method == "POST":
        try:
            from utils import slugify
            display_name = (request.form.get("display_name") or "").strip()
            phone = (request.form.get("phone") or "").strip()
            website = (request.form.get("website") or "").strip()
            bio = (request.form.get("bio") or "").strip()
            role = (request.form.get("role") or "").strip().lower()
            if role not in ("owner", "agent"):
                role = (prof["role"] if prof and "role" in prof.keys() else "owner")

            slug = prof["public_slug"]
            if not slug and display_name:
                base = slugify(display_name)
                candidate = base
                i = 2
                while conn.execute(
                    "SELECT 1 FROM landlord_profiles WHERE public_slug=?", (candidate,)
                ).fetchone():
                    candidate = f"{base}-{i}"
                    i += 1
                slug = candidate

            conn.execute("""
                UPDATE landlord_profiles
                   SET display_name=?, phone=?, website=?, bio=?, role=?,
                       public_slug=COALESCE(?, public_slug)
                 WHERE landlord_id=?
            """, (display_name, phone, website, bio, role, slug, lid))
            conn.commit()
            prof = conn.execute(
                "SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)
            ).fetchone()
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
    prof = conn.execute(
        "SELECT * FROM landlord_profiles WHERE public_slug=?", (slug,)
    ).fetchone()
    if not prof:
        conn.close()
        return render_template("landlord_profile_public.html", profile=None), 404
    conn.execute(
        "UPDATE landlord_profiles SET profile_views=profile_views+1 WHERE landlord_id=?",
        (prof["landlord_id"],)
    )
    conn.commit()
    ll = conn.execute(
        "SELECT email FROM landlords WHERE id=?", (prof["landlord_id"],)
    ).fetchone()
    conn.close()
    return render_template(
        "landlord_profile_public.html",
        profile=prof,
        contact_email=ll["email"] if ll else ""
    )

@landlord_bp.route("/l/id/<int:lid>")
def landlord_public_by_id(lid):
    conn = get_db()
    prof = conn.execute(
        "SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)
    ).fetchone()
    if not prof:
        conn.close()
        return render_template("landlord_profile_public.html", profile=None), 404
    conn.execute(
        "UPDATE landlord_profiles SET profile_views=profile_views+1 WHERE landlord_id=?",
        (lid,)
    )
    conn.commit()
    ll = conn.execute(
        "SELECT email FROM landlords WHERE id=?", (lid,)
    ).fetchone()
    conn.close()
    return render_template(
        "landlord_profile_public.html",
        profile=prof,
        contact_email=ll["email"] if ll else ""
    )

# Houses (list/new/edit/delete)
@landlord_bp.route("/landlord/houses")
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

@landlord_bp.route("/landlord/houses/new", methods=["GET","POST"])
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

@landlord_bp.route("/landlord/houses/<int:hid>/delete", methods=["POST"])
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

# -------- Rooms helpers --------
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

def _room_counts(conn, hid):
    row = conn.execute("SELECT bedrooms_total FROM houses WHERE id=?", (hid,)).fetchone()
    max_rooms = int(row["bedrooms_total"]) if row else 0
    cnt = conn.execute("SELECT COUNT(*) AS c FROM rooms WHERE house_id=?", (hid,)).fetchone()["c"]
    return max_rooms, int(cnt)

# -------------------------------
# Photos (Phase 2: processing)
# -------------------------------

def _uploads_abs_dir():
    # absolute path to 'static/uploads/houses'
    base = current_app.root_path
    return os.path.join(base, UPLOADS_HOUSES_DIR)

def _ensure_uploads_dir():
    os.makedirs(_uploads_abs_dir(), exist_ok=True)

def _unique_jpg_name():
    return f"{uuid.uuid4().hex}.jpg"

def _add_watermark(img: Image.Image, text: str) -> Image.Image:
    # draw subtle bottom-right watermark with padding
    draw = ImageDraw.Draw(img)
    W, H = img.size
    # font: default PIL font (avoid external deps)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    # scale watermark size based on image width
    base_font_px = max(12, min(24, W // 40))  # roughly 2.5% of width
    if font is None or getattr(font, "size", None) != base_font_px:
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
    # text size
    tw, th = draw.textbbox((0, 0), text, font=font)[2:]
    pad = max(8, W // 100)
    x = W - tw - pad
    y = H - th - pad
    # draw subtle shadow box for legibility
    box_pad = 4
    draw.rectangle([x - box_pad, y - box_pad, x + tw + box_pad, y + th + box_pad],
                   fill=(0, 0, 0, 90))
    # draw text (white)
    draw.text((x, y), text, fill=(255, 255, 255), font=font)
    return img

def _process_image(file_storage) -> tuple:
    """
    Returns (final_bytes, width, height) where final_bytes is a BytesIO buffer of JPEG data.
    """
    file_storage.stream.seek(0)
    with Image.open(file_storage.stream) as im:
        # Convert to RGB (drop alpha)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        elif im.mode == "L":
            im = im.convert("RGB")

        # Resize to max
        im.thumbnail((IMAGE_MAX_WIDTH, IMAGE_MAX_HEIGHT), Image.LANCZOS)

        # Watermark
        im = _add_watermark(im, WATERMARK_TEXT)

        # Compress to <= target bytes
        quality = 85
        min_quality = 50
        step = 5

        def encode(q):
            bio = io.BytesIO()
            im.save(bio, format="JPEG", optimize=True, progressive=True, quality=q)
            return bio

        bio = encode(quality)
        while bio.tell() > IMAGE_TARGET_BYTES and quality > min_quality:
            quality = max(min_quality, quality - step)
            bio = encode(quality)

        data = bio.getvalue()
        width, height = im.size
        return io.BytesIO(data), width, height

@landlord_bp.route("/landlord/houses/<int:hid>/photos")
def house_photos(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    rows = conn.execute("""
        SELECT id, file_path, width, height, bytes, is_primary
          FROM house_images
         WHERE house_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (hid,)).fetchall()
    conn.close()

    images = list(rows)
    current_count = len(images)
    remaining = max(0, HOUSE_IMAGES_MAX - current_count)

    return render_template(
        "house_photos.html",
        house=house,
        images=images,
        max_images=HOUSE_IMAGES_MAX,
        remaining=remaining
    )

@landlord_bp.route("/landlord/houses/<int:hid>/photos/upload", methods=["POST"])
def house_photos_upload(hid):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    # count existing
    row = conn.execute("SELECT COUNT(*) AS c FROM house_images WHERE house_id=?", (hid,)).fetchone()
    existing = int(row["c"]) if row else 0
    remaining = max(0, HOUSE_IMAGES_MAX - existing)
    if remaining <= 0:
        conn.close()
        flash(f"Limit reached: {HOUSE_IMAGES_MAX} photos per house.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    files = request.files.getlist("photos")
    if not files:
        conn.close()
        flash("Please choose one or more images.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    _ensure_uploads_dir()
    saved = 0
    errors = 0

    # find next sort_order start
    srow = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS m FROM house_images WHERE house_id=?", (hid,)).fetchone()
    sort_order = int(srow["m"]) if srow and srow["m"] is not None else 0

    for fs in files:
        if saved >= remaining:
            break
        filename = fs.filename or ""
        if not allowed_image_ext(filename):
            errors += 1
            continue

        try:
            out_bytes, w, h = _process_image(fs)
        except Exception as e:
            print("[IMG] process error:", e)
            errors += 1
            continue

        # write to disk
        fname = _unique_jpg_name()
        rel_path = os.path.join("uploads", "houses", fname)   # relative under /static
        abs_path = os.path.join(current_app.root_path, "static", rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(out_bytes.getvalue())

        file_size = os.path.getsize(abs_path)

        # first image ever? set primary
        is_primary = 0
        if existing == 0 and saved == 0:
            is_primary = 1

        sort_order += 1
        conn.execute("""
            INSERT INTO house_images(house_id, filename, file_path, width, height, bytes, is_primary, sort_order, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (hid, fname, rel_path, w, h, int(file_size), is_primary, sort_order, dt.utcnow().isoformat()))
        conn.commit()
        saved += 1

    conn.close()

    if saved:
        flash(f"Uploaded {saved} photo(s).", "ok")
    if errors:
        flash(f"{errors} file(s) were skipped due to errors or unsupported types.", "error")

    return redirect(url_for("landlord.house_photos", hid=hid))

@landlord_bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/primary", methods=["POST"])
def house_photos_primary(hid, img_id):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    # ensure img belongs to house
    img = conn.execute("SELECT id FROM house_images WHERE id=? AND house_id=?", (img_id, hid)).fetchone()
    if not img:
        conn.close()
        flash("Photo not found.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    conn.execute("UPDATE house_images SET is_primary=0 WHERE house_id=?", (hid,))
    conn.execute("UPDATE house_images SET is_primary=1 WHERE id=? AND house_id=?", (img_id, hid))
    conn.commit()
    conn.close()
    flash("Primary photo updated.", "ok")
    return redirect(url_for("landlord.house_photos", hid=hid))

@landlord_bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/delete", methods=["POST"])
def house_photos_delete(hid, img_id):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    img = conn.execute("SELECT id, file_path, is_primary FROM house_images WHERE id=? AND house_id=?", (img_id, hid)).fetchone()
    if not img:
        conn.close()
        flash("Photo not found.", "error")
        return redirect(url_for("landlord.house_photos", hid=hid))

    # remove from disk
    try:
        abs_path = os.path.join(current_app.root_path, "static", img["file_path"])
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except Exception as e:
        print("[IMG] delete file error:", e)

    # delete db row
    conn.execute("DELETE FROM house_images WHERE id=? AND house_id=?", (img_id, hid))
    conn.commit()

    # if deleted was primary, set another as primary (oldest first)
    if int(img["is_primary"]) == 1:
        row = conn.execute("""
            SELECT id FROM house_images
             WHERE house_id=?
             ORDER BY sort_order ASC, id ASC
             LIMIT 1
        """, (hid,)).fetchone()
        if row:
            conn.execute("UPDATE house_images SET is_primary=1 WHERE id=?", (row["id"],))
            conn.commit()

    conn.close()
    flash("Photo deleted.", "ok")
    return redirect(url_for("landlord.house_photos", hid=hid))
