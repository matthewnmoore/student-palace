# landlord/rooms_all.py
from __future__ import annotations

from collections import OrderedDict
from flask import render_template, redirect, url_for, flash
from db import get_db
from utils import current_landlord_id, require_landlord
from . import bp


@bp.route("/landlord/rooms-all")
def rooms_all():
    """Grouped list of every room for the current landlord, by City → House."""
    r = require_landlord()
    if r:
        return r

    lid = current_landlord_id()
    conn = get_db()

    # Pull houses and rooms for this landlord
    rows = conn.execute(
        """
        SELECT
            h.id              AS house_id,
            h.title           AS house_title,
            h.city            AS city,
            COALESCE(h.bills_option, 'no') AS bills_option,
            r.id              AS room_id,
            r.name            AS room_name,
            r.price_pcm       AS price_pcm,
            COALESCE(r.bed_size,'')        AS bed_size,
            COALESCE(r.ensuite,0)          AS ensuite,
            COALESCE(r.couples_ok,0)       AS couples_ok,
            COALESCE(r.is_let,0)           AS is_let,
            r.let_until                     AS let_until
        FROM houses h
        LEFT JOIN rooms r ON r.house_id = h.id
        WHERE h.landlord_id = ?
        ORDER BY h.city ASC, h.title ASC, h.id ASC, r.id ASC
        """,
        (lid,),
    ).fetchall()
    conn.close()

    # Shape into: OrderedDict[city] -> list of houses; each house has rooms list
    grouped: "OrderedDict[str, list[dict]]" = OrderedDict()
    by_house_key = {}  # (city, house_id) -> house dict

    for row in rows:
        city = row["city"] or "—"
        if city not in grouped:
            grouped[city] = []

        hk = (city, row["house_id"])
        if hk not in by_house_key:
            house = {
                "id": row["house_id"],
                "title": row["house_title"],
                "city": city,
                "bills_option": (row["bills_option"] or "no").lower(),
                "rooms": [],
            }
            grouped[city].append(house)
            by_house_key[hk] = house
        house = by_house_key[hk]

        # Room may be NULL when a house has no rooms yet (because of LEFT JOIN)
        if row["room_id"] is not None:
            house["rooms"].append(
                {
                    "id": row["room_id"],
                    "name": row["room_name"],
                    "price_pcm": row["price_pcm"],
                    "bed_size": row["bed_size"],
                    "ensuite": int(row["ensuite"]),
                    "couples_ok": int(row["couples_ok"]),
                    "is_let": int(row["is_let"]),
                    "let_until": row["let_until"] or "",
                }
            )

    return render_template("landlord_rooms_all.html", grouped=grouped)
