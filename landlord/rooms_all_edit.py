# landlord/rooms_all_edit.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from datetime import date, timedelta
from db import get_db
from utils import require_landlord, current_landlord_id
from . import bp
from utils_summaries import recompute_house_summaries


def _next_june_30(today: date) -> date:
    y = today.year + (1 if (today.month, today.day) > (6, 30) else 0)
    return date(y, 6, 30)


def _parse_iso(d: str) -> date | None:
    try:
        return date.fromisoformat((d or "").strip())
    except Exception:
        return None


@bp.route("/landlord/portfolio/edit")
def rooms_portfolio_edit():
    """All rooms across all the landlord’s houses, with per-room edit controls."""
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()

    conn = get_db()
    # Pull rooms + house context for this landlord
    rows = conn.execute(
        """
        SELECT
          r.id             AS room_id,
          r.house_id       AS house_id,
          r.name           AS room_name,
          r.price_pcm      AS price_pcm,
          r.is_let         AS is_let,
          r.let_until      AS let_until,
          r.available_from AS available_from,
          r.bed_size       AS bed_size,
          COALESCE(r.ensuite,0)     AS ensuite,
          COALESCE(r.couples_ok,0)  AS couples_ok,
          h.title          AS house_title,
          h.city           AS city
        FROM rooms r
        JOIN houses h ON h.id = r.house_id
        WHERE h.landlord_id = ?
        ORDER BY h.city ASC, h.title ASC, r.is_let ASC, r.id ASC
        """,
        (lid,),
    ).fetchall()
    conn.close()

    return render_template("landlord_rooms_all_edit.html", rooms=rows)


@bp.route("/landlord/portfolio/edit/apply/<int:rid>", methods=["POST"])
def rooms_portfolio_edit_apply(rid: int):
    """Apply per-room edits (price + availability) to a single room."""
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()

    conn = get_db()
    # Verify the room belongs to this landlord via its house
    row = conn.execute(
        """
        SELECT r.id, r.house_id
        FROM rooms r
        JOIN houses h ON h.id = r.house_id
        WHERE r.id = ? AND h.landlord_id = ?
        """,
        (rid, lid),
    ).fetchone()

    if not row:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("landlord.rooms_portfolio_edit"))

    # ---- Price (optional) ----
    price_in = (request.form.get("price_pcm") or "").strip().replace(",", "")
    set_price = None
    if price_in != "":
        try:
            set_price = max(0, int(float(price_in)))
        except Exception:
            set_price = None

    # ---- Availability (optional, same defaults/rules as bulk) ----
    vals = [str(v).strip().lower() for v in request.form.getlist("is_let")]
    is_let = 1 if ("1" in vals or "on" in vals or "true" in vals) else 0
    let_until_in = (request.form.get("let_until") or "").strip()
    available_from_in = (request.form.get("available_from") or "").strip()

    today = date.today()
    lu = _parse_iso(let_until_in)
    af = _parse_iso(available_from_in)

    if is_let:
        # Marking as let: default let_until = 30 June next year; available_from = +1 day
        if not lu:
            lu = _next_june_30(today)
        if not af or af <= lu:
            af = lu + timedelta(days=1)
    else:
        # Marking available: default available_from = today; let_until = day before
        if not af:
            af = today
        if not lu or lu >= af:
            lu = af - timedelta(days=1)

    # Build update
    sets = []
    params = []

    if set_price is not None:
        sets.append("price_pcm = ?")
        params.append(set_price)

    sets.extend(["is_let = ?", "let_until = ?", "available_from = ?"])
    params.extend([is_let, lu.isoformat() if lu else None, af.isoformat() if af else None])

    params.append(rid)
    conn.execute(f"UPDATE rooms SET {', '.join(sets)} WHERE id = ?", params)

    # Recompute house rollups for public pages
    recompute_house_summaries(conn, row["house_id"])

    conn.commit()
    conn.close()

    flash("Room updated.", "ok")
    return redirect(url_for("landlord.rooms_portfolio_edit"))
