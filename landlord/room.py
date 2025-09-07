from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt, date, timedelta
from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none
from .helpers import room_form_values, room_counts
from . import bp

# ✅ summaries recompute
from utils_summaries import recompute_house_summaries
from utils_summaries import recompute_house_summaries_disabled


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
        # available_from stays as provided (could be today/future)
        return

    # is_let == 1
    if not available_from and let_until:
        try:
            y, m, d = map(int, let_until.split("-"))
            next_day = date(y, m, d) + timedelta(days=1)
            vals["available_from"] = next_day.isoformat()
        except Exception:
            # If parsing fails, leave as-is (optional)
            pass


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
        recompute_house_summaries_disabled(conn, hid)

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
        recompute_house_summaries_disabled(conn, hid)

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
    recompute_house_summaries_disabled(conn, hid)

    conn.commit()
    conn.close()
    flash("Room deleted.", "ok")
    return redirect(url_for("landlord.rooms_list", hid=hid))
