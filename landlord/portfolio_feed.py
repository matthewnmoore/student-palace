# landlord/portfolio_feed.py
from __future__ import annotations

from flask import render_template
from db import get_db
from utils import require_landlord, current_landlord_id
from . import bp


@bp.route("/landlord/portfolio_feed")
def portfolio_feed():
    """Read-only feed: show all rooms across all houses, compact format."""
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()

    conn = get_db()
    rows = conn.execute(
        """
        SELECT
          h.id           AS house_id,
          h.title        AS house_title,
          h.city         AS city,
          h.bills_option AS bills_option,
          r.id           AS room_id,
          r.name         AS room_name,
          r.price_pcm    AS price_pcm,
          r.is_let       AS is_let,
          r.let_until    AS let_until,
          r.available_from AS available_from
        FROM houses h
        JOIN rooms r ON r.house_id = h.id
        WHERE h.landlord_id = ?
        ORDER BY h.city ASC, h.title ASC, r.name ASC
        """,
        (lid,),
    ).fetchall()
    conn.close()

    return render_template("landlord_portfolio_feed.html", rows=rows)
