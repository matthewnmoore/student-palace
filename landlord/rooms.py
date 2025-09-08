from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt, date, timedelta
from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none
from .helpers import room_form_values, room_counts
from . import bp

# ✅ summaries recompute
from utils_summaries import recompute_house_summaries


def _parse_is_let(request):
    """
    Robustly parse the 'is_let' checkbox.
    We expect a hidden 0 and an optional checkbox 1; use getlist to be safe.
    """
    values = [v.strip() for v in request.form.getlist("is_let")]
    return 1 if "1" in values else 0


def _parse_checkbox(request, name: str) -> int:
    """
    Robustly parse a single checkbox (with or without a hidden 0 input).
    Returns 1 if the checkbox was submitted as '1'/'on'/True, else 0.
    """
    values = [str(v).strip().lower() for v in request.form.getlist(name)]
    return 1 if ("1" in values or "on" in values or "true" in values) else 0


def _normalize_dates_for_is_let(vals: dict) -> None:
    """
    Mirror portfolio logic:
    - If let: let_until = next 30 June (if missing), available_from = let_until + 1 (if missing/<=).
    - If available: available_from = today (if missing), let_until = day before available_from.
    """
    from datetime import datetime as dt, date, timedelta

    def _to_date(iso_str: str) -> date | None:
        try:
            return dt.strptime((iso_str or "").strip(), "%Y-%m-%d").date()
        except Exception:
            return None

    def _next_june_30(today: date) -> date:
        y = today.year + (1 if (today.month, today.day) > (6, 30) else 0)
        return date(y, 6, 30)

    is_let = int(vals.get("is_let") or 0)
    af = _to_date(vals.get("available_from") or "")
    lu = _to_date(vals.get("let_until") or "")
    today = date.today()

    if is_let:
        # If let: ensure let_until and available_from follow the pattern
        if not lu:
            lu = _next_june_30(today)
        if not af or af <= lu:
            af = lu + timedelta(days=1)
    else:
        # If available: ensure available_from has a value, and let_until is day before
        if not af:
            af = today
        if not lu or lu >= af:
            lu = af - timedelta(days=1)

    vals["available_from"] = af.isoformat() if af else ""
    vals["let_until"] = lu.isoformat() if lu else ""


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

        # ✅ Force correct parsing of checkboxes
        vals["is_let"] = _parse_is_let(request)
        vals["couples_ok"] = _parse_checkbox(request, "couples_ok")
        vals["disabled_ok"] = _parse_checkbox(request, "disabled_ok")
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

        # ✅ Recompute summaries
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

        # ✅ Force correct parsing of checkboxes
        vals["is_let"] = _parse_is_let(request)
        vals["couples_ok"] = _parse_checkbox(request, "couples_ok")
        vals["disabled_ok"] = _parse_checkbox(request, "disabled_ok")
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

        # ✅ Recompute summaries
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

    # ✅ Recompute summaries
    recompute_house_summaries(conn, hid)

    conn.commit()
    conn.close()
    flash("Room deleted.", "ok")
    return redirect(url_for("landlord.rooms_list", hid=hid))
