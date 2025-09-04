# landlord/bulk.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from datetime import date, timedelta
from db import get_db
from utils import require_landlord, current_landlord_id, owned_house_or_none
from . import bp
from utils_summaries import recompute_house_summaries


def _next_june_30(today: date) -> date:
    y = today.year + (1 if (today.month, today.day) > (6, 30) else 0)
    return date(y, 6, 30)


def _parse_iso(d: str) -> date | None:
    try:
        return date.fromisoformat(d.strip())
    except Exception:
        return None


@bp.route("/landlord/bulk")
def bulk_edit():
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()

    conn = get_db()
    rows = conn.execute(
        """
        SELECT
          h.id, h.title, h.city, h.letting_type,
          COALESCE(COUNT(r.id), 0) AS rooms_total,
          COALESCE(SUM(CASE WHEN r.is_let=0 THEN 1 ELSE 0 END), 0) AS rooms_avail,
          CAST(AVG(NULLIF(r.price_pcm,0)) AS INT) AS avg_price_pcm
        FROM houses h
        LEFT JOIN rooms r ON r.house_id = h.id
        WHERE h.landlord_id = ?
        GROUP BY h.id
        ORDER BY h.city ASC, h.title ASC, h.id ASC
        """,
        (lid,),
    ).fetchall()
    conn.close()

    return render_template("landlord_bulk_edit.html", houses=rows)


@bp.route("/landlord/bulk/apply/<int:hid>", methods=["POST"])
def bulk_apply(hid: int):
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()

    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.bulk_edit"))

    # ---- Price (optional) ----
    price_in = (request.form.get("price_pcm") or "").strip().replace(",", "")
    set_price = None
    if price_in != "":
        try:
            set_price = max(0, int(float(price_in)))
        except Exception:
            set_price = None

    # ---- Availability (optional) ----
    is_let = 1 if (request.form.getlist("is_let") and request.form.getlist("is_let")[0] in ("1", "on", "true", "True")) else 0
    let_until_in = (request.form.get("let_until") or "").strip()
    available_from_in = (request.form.get("available_from") or "").strip()

    today = date.today()
    lu = _parse_iso(let_until_in)
    af = _parse_iso(available_from_in)

    if is_let:
        # If marking as let:
        # default let_until = 30 June next year, available_from = +1 day
        if not lu:
            lu = _next_june_30(today)
        if not af or af <= lu:
            af = lu + timedelta(days=1)
    else:
        # If marking as available:
        # default available_from = today, let_until = day before (keeps af > lu)
        if not af:
            af = today
        if not lu or lu >= af:
            lu = af - timedelta(days=1)

    # ---- Build updates ----
    sets = []
    params = []

    if set_price is not None:
        sets.append("price_pcm = ?")
        params.append(set_price)

    # We always allow bulk availability change (based on checkbox state)
    sets.extend(["is_let = ?", "let_until = ?", "available_from = ?"])
    params.extend([is_let, lu.isoformat() if lu else None, af.isoformat() if af else None])

    params.append(hid)

    conn.execute(f"UPDATE rooms SET {', '.join(sets)} WHERE house_id = ?", params)

    # Recompute public-facing rollups
    recompute_house_summaries(conn, hid)

    conn.commit()
    conn.close()

    flash("Bulk update applied to all rooms in the house.", "ok")
    return redirect(url_for("landlord.bulk_edit"))
