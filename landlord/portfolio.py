# landlord/portfolio.py
from __future__ import annotations

from flask import render_template
from db import get_db
from utils import require_landlord, current_landlord_id
from . import bp


@bp.route("/landlord/portfolio")
def portfolio():
    """
    Flat feed of all rooms across all houses for the current landlord.
    Matches the fields expected by templates/landlord_portfolio.html.
    """
    r = require_landlord()
    if r:
        return r

    lid = current_landlord_id()
    conn = get_db()

    rows = conn.execute(
        """
        SELECT
          r.id                  AS room_id,
          r.name                AS room_name,
          r.price_pcm           AS price_pcm,
          COALESCE(r.is_let,0)  AS is_let,
          r.let_until           AS let_until,
          r.available_from      AS available_from,

          h.id                  AS house_id,
          h.title               AS house_title,
          h.city                AS city,
          COALESCE(h.bills_option, 'no') AS bills_option
        FROM houses h
        JOIN rooms r ON r.house_id = h.id
        WHERE h.landlord_id = ?
        ORDER BY h.city ASC, h.title ASC, r.id ASC
        """,
        (lid,),
    ).fetchall()

    conn.close()
    return render_template("landlord_portfolio.html", rows=rows)
