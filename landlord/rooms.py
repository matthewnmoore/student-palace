from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt, date, timedelta
from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none
from .helpers import room_form_values, room_counts
from . import bp
from utils_summaries import recompute_house_summaries


# -------- checkbox helpers --------
def _parse_is_let(request) -> int:
    # We submit a hidden 0 and a checkbox 1; use getlist so unticked -> ["0"], ticked -> ["1","0"].
    values = [v.strip() for v in request.form.getlist("is_let")]
    return 1 if "1" in values else 0


def _parse_checkbox(request, name: str) -> int:
    values = [str(v).strip().lower() for v in request.form.getlist(name)]
    return 1 if ("1" in values or "on" in values or "true" in values) else 0


# -------- date healing (do this ONCE, here) --------
def _to_date(s: str) -> date | None:
    if not s:
        return None
    try:
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)
    except Exception:
        return None


def _iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def _june_30_next_year(today: date) -> date:
    return date(today.year + 1, 6, 30)


def _heal_availability(vals: dict) -> None:
    """
    Make available_from / let_until consistent with is_let.
    We do this after we’ve parsed is_let correctly from getlist().
    """
    is_let = int(vals.get("is_let") or 0)
    today = date.today()

    af = _to_date(vals.get("available_from") or "")
    lu = _to_date(vals.get("let_until") or "")

    if is_let:
        # If let, default let_until and ensure available_from is the day after
        if not lu:
            lu = _june_30_next_year(today)
        if not af or af <= lu:
            af = lu + timedelta(days=1)
    else:
        # Not let: clearly available now (or on the chosen past date)
        if not af or af > today:
            af = today
        # Keep a clean boundary for searches: let_until = day before available_from
        lu = af - timedelta(days=1)

    vals["available_from"] = _iso(af)
    vals["let_until"] = _iso(lu)


# ================= Routes =================

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
    rows = conn.execute(
        "SELECT * FROM rooms WHERE house_id=? ORDER BY id ASC", (hid,)
    ).fetchall()
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
        max_rooms=max_rooms,
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
        # Parse raw values (no date healing inside the helper)
        vals, errors = room_form_values(request)

        # Overwrite checkboxes with robust parsing
        vals["is_let"] = _parse_is_let(request)
        vals["couples_ok"] = _parse_checkbox(request, "couples_ok")
        vals["disabled_ok"] = _parse_checkbox(request, "disabled_ok")

        # Heal availability ONCE based on the correct is_let
        _heal_availability(vals)

        if errors:
            for e in errors:
                flash(e, "error")
            conn.close()
            return render_template("room_form.html", house=house, form=vals, mode="new")

        cur = conn.execute(
            """
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
            """,
            (
                hid, vals["name"], vals["description"], vals["ensuite"], vals["bed_size"], vals["tv"],
                vals["desk_chair"], vals["wardrobe"], vals["chest_drawers"],
                vals["lockable_door"], vals["wired_internet"], vals["room_size"],
                vals["price_pcm"], vals["safe"], vals["dressing_table"], vals["mirror"],
                vals["bedside_table"], vals["blinds"], vals["curtains"], vals["sofa"],
                vals["couples_ok"], vals["disabled_ok"],
                vals["is_let"], vals["available_from"], vals["let_until"],
                dt.utcnow().isoformat()
            ),
        )
        rid = cur.lastrowid

        recompute_house_summaries(conn, hid)
        conn.commit()
        conn.close()
        flash("Room added.", "ok")

        action = request.form.get("action")
        return (
            redirect(url_for("landlord.room_edit", hid=hid, rid=rid))
            if action == "save_only"
            else redirect(url_for("landlord.rooms_list", hid=hid))
        )

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

    room = conn.execute(
        "SELECT * FROM rooms WHERE id=? AND house_id=?", (rid, hid)
    ).fetchone()
    if not room:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.rooms_list", hid=hid))

    if request.method == "POST":
        vals, errors = room_form_values(request)

        # Robust checkbox parsing
        vals["is_let"] = _parse_is_let(request)
        vals["couples_ok"] = _parse_checkbox(request, "couples_ok")
        vals["disabled_ok"] = _parse_checkbox(request, "disabled_ok")

        # Single source of truth for availability healing
        _heal_availability(vals)

        if errors:
            for e in errors:
                flash(e, "error")
            conn.close()
            return render_template("room_form.html", house=house, form=vals, mode="edit", room=room)

        conn.execute(
            """
            UPDATE rooms SET
              name=?, description=?, ensuite=?, bed_size=?, tv=?, desk_chair=?, wardrobe=?, chest_drawers=?, 
              lockable_door=?, wired_internet=?, room_size=?,
              price_pcm=?, safe=?, dressing_table=?, mirror=?,
              bedside_table=?, blinds=?, curtains=?, sofa=?,
              couples_ok=?, disabled_ok=?,
              is_let=?, available_from=?, let_until=?
            WHERE id=? AND house_id=?
            """,
            (
                vals["name"], vals["description"], vals["ensuite"], vals["bed_size"], vals["tv"], vals["desk_chair"],
                vals["wardrobe"], vals["chest_drawers"], vals["lockable_door"], vals["wired_internet"],
                vals["room_size"],
                vals["price_pcm"], vals["safe"], vals["dressing_table"], vals["mirror"],
                vals["bedside_table"], vals["blinds"], vals["curtains"], vals["sofa"],
                vals["couples_ok"], vals["disabled_ok"],
                vals["is_let"], vals["available_from"], vals["let_until"],
                rid, hid,
            ),
        )

        recompute_house_summaries(conn, hid)
        conn.commit()
        conn.close()
        flash("Room updated.", "ok")

        action = request.form.get("action")
        return (
            redirect(url_for("landlord.room_edit", hid=hid, rid=rid))
            if action == "save_only"
            else redirect(url_for("landlord.rooms_list", hid=hid))
        )

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
    recompute_house_summaries(conn, hid)
    conn.commit()
    conn.close()
    flash("Room deleted.", "ok")
    return redirect(url_for("landlord.rooms_list", hid=hid))
