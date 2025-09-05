# landlord/rooms.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt, date, timedelta

from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none, clean_bool
from . import bp

# summaries recompute
from utils_summaries import recompute_house_summaries


def _parse_is_let(request):
    """
    Robustly parse the 'is_let' checkbox.
    We expect a hidden 0 and an optional checkbox 1; use getlist to be safe.
    """
    values = [v.strip() for v in request.form.getlist("is_let")]
    return 1 if "1" in values else 0


def _parse_uk_date(value: str) -> str:
    """
    Accepts 'DD/MM/YYYY' (UK) or 'YYYY-MM-DD' (HTML date input) and returns ISO 'YYYY-MM-DD'.
    Returns '' if empty or invalid.
    """
    if not value:
        return ""
    value = value.strip()
    if not value:
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = dt.strptime(value, fmt).date()
            return d.isoformat()
        except Exception:
            continue
    return ""


def _to_date(iso_str: str) -> date | None:
    """Convert 'YYYY-MM-DD' to date or None."""
    if not iso_str:
        return None
    try:
        return dt.strptime(iso_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def _june_30_next_year(today: date) -> date:
    """Always 30 June next calendar year from 'today'."""
    return date(today.year + 1, 6, 30)


def _normalize_dates_for_is_let(vals: dict) -> None:
    """
    Basic server-side guard:
    - If not let, clear let_until (so it can’t linger).
    - If let, ensure available_from is present; if missing but let_until exists,
      set available_from = let_until + 1 day (matches the JS behaviour).
    """
    is_let = int(vals.get("is_let") or 0)
    let_until = (vals.get("let_until") or "").strip()
    available_from = (vals.get("available_from") or "").strip()

    if not is_let:
        vals["let_until"] = ""  # clear
        return

    if not available_from and let_until:
        try:
            y, m, d = map(int, let_until.split("-"))
            next_day = date(y, m, d) + timedelta(days=1)
            vals["available_from"] = next_day.isoformat()
        except Exception:
            pass


def room_form_values(request):
    name = (request.form.get("name") or "").strip()
    ensuite = clean_bool("ensuite")
    bed_size = (request.form.get("bed_size") or "").strip()
    tv = clean_bool("tv")
    desk_chair = clean_bool("desk_chair")
    wardrobe = clean_bool("wardrobe")
    chest_drawers = clean_bool("chest_drawers")
    lockable_door = clean_bool("lockable_door")
    wired_internet = clean_bool("wired_internet")
    room_size = (request.form.get("room_size") or "").strip()

    # NEW FIELD: description
    description = (request.form.get("description") or "").strip()

    # NEW FIELDS
    raw_price = (request.form.get("price_pcm") or "").strip()
    try:
        price_pcm = int(raw_price.replace(",", ""))
    except Exception:
        price_pcm = 0
    safe = clean_bool("safe")
    dressing_table = clean_bool("dressing_table")
    mirror = clean_bool("mirror")
    bedside_table = clean_bool("bedside_table")
    blinds = clean_bool("blinds")
    curtains = clean_bool("curtains")
    sofa = clean_bool("sofa")

    # NEW SEARCHABLE FIELDS
    couples_ok = clean_bool("couples_ok")
    disabled_ok = clean_bool("disabled_ok")

    # NEW AVAILABILITY FIELDS
    is_let = clean_bool("is_let")
    available_from_in = (request.form.get("available_from") or "").strip()
    let_until_in = (request.form.get("let_until") or "").strip()

    available_from_iso = _parse_uk_date(available_from_in)
    let_until_iso = _parse_uk_date(let_until_in)

    # Self-healing date logic
    today = date.today()
    af = _to_date(available_from_iso)
    lu = _to_date(let_until_iso)

    if is_let:
        # Default let_until to 30 June next year if missing
        if not lu:
            lu = _june_30_next_year(today)
        # available_from must be day after let_until
        if not af or af <= lu:
            af = lu + timedelta(days=1)
    else:
        # Room available now
        if not af:
            af = today
        # Force let_until to two days before available_from
        lu = af - timedelta(days=2)

    # Back to ISO for DB
    available_from_iso = _iso(af)
    let_until_iso = _iso(lu)

    errors = []
    if not name:
        errors.append("Room name is required.")
    if len(name) > 20:
        errors.append("Room name cannot be longer than 20 characters.")
    if len(description) > 1200:
        errors.append("Room description cannot be longer than 1200 characters.")
    if bed_size not in ("Single", "Small double", "Double", "King"):
        errors.append("Please choose a valid bed size.")

    return ({
        "name": name,
        "description": description,
        "ensuite": ensuite,
        "bed_size": bed_size,
        "tv": tv,
        "desk_chair": desk_chair,
        "wardrobe": wardrobe,
        "chest_drawers": chest_drawers,
        "lockable_door": lockable_door,
        "wired_internet": wired_internet,
        "room_size": room_size,
        "price_pcm": price_pcm,
        "safe": safe,
        "dressing_table": dressing_table,
        "mirror": mirror,
        "bedside_table": bedside_table,
        "blinds": blinds,
        "curtains": curtains,
        "sofa": sofa,
        "couples_ok": couples_ok,
        "disabled_ok": disabled_ok,
        "is_let": is_let,
        "available_from": available_from_iso,
        "let_until": let_until_iso,
    }, errors)


def room_counts(conn, hid):
    """Return (max_rooms, current_count) for a given house."""
    row = conn.execute(
        "SELECT bedrooms_total FROM houses WHERE id=?",
        (hid,)
    ).fetchone()
    max_rooms = int(row["bedrooms_total"]) if row else 0
    cnt = conn.execute(
        "SELECT COUNT(*) AS c FROM rooms WHERE house_id=?",
        (hid,)
    ).fetchone()["c"]
    return max_rooms, int(cnt)


@bp.route("/landlord/houses/<int:hid>/rooms")
def rooms_list(hid):
    r = require_landlord()
    if r:
        return r
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


@bp.route("/landlord/houses/<int:hid>/rooms/new", methods=["GET", "POST"])
def room_new(hid):
    r = require_landlord()
    if r:
        return r
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

        # Force correct parsing of is_let regardless of helper behaviour
        vals["is_let"] = _parse_is_let(request)
        _normalize_dates_for_is_let(vals)

        if errors:
            for e in errors:
                flash(e, "error")
            conn.close()
            return render_template("room_form.html", house=house, form=vals, mode="new")

        cur = conn.execute("""
          INSERT INTO rooms(
            house_id, name, description, ensuite, bed_size, tv, desk_chair, wardrobe, chest_drawers,
            lockable_door, wired_internet, room_size,
            price_pcm, safe, dressing_table, mirror,
            bedside_table, blinds, curtains, sofa,
            couples_ok, disabled_ok,
            is_let, available_from, let_until,
            created_at
          )
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            hid, vals["name"], vals["description"], vals["ensuite"], vals["bed_size"], vals["tv"],
            vals["desk_chair"], vals["wardrobe"], vals["chest_drawers"],
            vals["lockable_door"], vals["wired_internet"], vals["room_size"],
            vals["price_pcm"], vals["safe"], vals["dressing_table"], vals["mirror"],
            vals["bedside_table"], vals["blinds"], vals["curtains"], vals["sofa"],
            vals["couples_ok"], vals["disabled_ok"],
            vals["is_let"], vals["available_from"], vals["let_until"],
            dt.utcnow().isoformat()
        ))
        rid = cur.lastrowid

        # Recompute summaries
        recompute_house_summaries(conn, hid)

        conn.commit()
        conn.close()
        flash("Room added.", "ok")

        action = request.form.get("action")
        if action == "save_only":
            return redirect(url_for("landlord.room_edit", hid=hid, rid=rid))
        else:
            return redirect(url_for("landlord.rooms_list", hid=hid))

    conn.close()
    return render_template("room_form.html", house=house, form={}, mode="new")


@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/edit", methods=["GET", "POST"])
def room_edit(hid, rid):
    r = require_landlord()
    if r:
        return r
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

        # Force correct parsing of is_let regardless of helper behaviour
        vals["is_let"] = _parse_is_let(request)
        _normalize_dates_for_is_let(vals)

        if errors:
            for e in errors:
                flash(e, "error")
            conn.close()
            return render_template("room_form.html", house=house, form=vals, mode="edit", room=room)

        conn.execute("""
          UPDATE rooms SET
            name=?, description=?, ensuite=?, bed_size=?, tv=?, desk_chair=?, wardrobe=?, chest_drawers=?, 
            lockable_door=?, wired_internet=?, room_size=?,
            price_pcm=?, safe=?, dressing_table=?, mirror=?,
            bedside_table=?, blinds=?, curtains=?, sofa=?,
            couples_ok=?, disabled_ok=?,
            is_let=?, available_from=?, let_until=?
          WHERE id=? AND house_id=?
        """, (
            vals["name"], vals["description"], vals["ensuite"], vals["bed_size"], vals["tv"], vals["desk_chair"],
            vals["wardrobe"], vals["chest_drawers"], vals["lockable_door"], vals["wired_internet"],
            vals["room_size"],
            vals["price_pcm"], vals["safe"], vals["dressing_table"], vals["mirror"],
            vals["bedside_table"], vals["blinds"], vals["curtains"], vals["sofa"],
            vals["couples_ok"], vals["disabled_ok"],
            vals["is_let"], vals["available_from"], vals["let_until"],
            rid, hid
        ))

        # Recompute summaries
        recompute_house_summaries(conn, hid)

        conn.commit()
        conn.close()
        flash("Room updated.", "ok")

        action = request.form.get("action")
        if action == "save_only":
            return redirect(url_for("landlord.room_edit", hid=hid, rid=rid))
        else:
            return redirect(url_for("landlord.rooms_list", hid=hid))

    form = dict(room)
    conn.close()
    return render_template("room_form.html", house=house, form=form, mode="edit", room=room)


@bp.route("/landlord/houses/<int:hid>/rooms/<int:rid>/delete", methods=["POST"])
def room_delete(hid, rid):
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        return redirect(url_for("landlord.landlord_houses"))
    conn.execute("DELETE FROM rooms WHERE id=? AND house_id=?", (rid, hid))

    # Recompute summaries
    recompute_house_summaries(conn, hid)

    conn.commit()
    conn.close()
    flash("Room deleted.", "ok")
    return redirect(url_for("landlord.rooms_list", hid=hid))
