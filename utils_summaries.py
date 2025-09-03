# utils_summaries.py
from __future__ import annotations
import json
from typing import Dict, Any
from sqlite3 import Connection

DOUBLE_SIZES = {"Small double", "Double", "King"}

def recompute_house_summaries(conn: Connection, house_id: int) -> Dict[str, Any]:
    """
    Recalculate and persist summary fields on houses for the given house_id.
    Returns the dict of values written.
    """
    rows = conn.execute("""
        SELECT
            name,
            COALESCE(ensuite,0)            AS ensuite,
            COALESCE(is_let,0)             AS is_let,
            COALESCE(price_pcm,0)          AS price_pcm,
            COALESCE(bed_size,'')          AS bed_size,
            COALESCE(couples_ok,0)         AS couples_ok
        FROM rooms
        WHERE house_id=?
    """, (house_id,)).fetchall()

    ensuites_total = 0
    available_rooms_total = 0
    available_prices_list = []   # list[dict{name, price}]
    double_beds_total = 0
    suitable_for_couples_total = 0

    for r in rows:
        if int(r["ensuite"]) == 1:
            ensuites_total += 1
        if (r["bed_size"] or "").strip() in DOUBLE_SIZES:
            double_beds_total += 1
        if int(r["couples_ok"]) == 1:
            suitable_for_couples_total += 1
        if int(r["is_let"]) == 0:
            available_rooms_total += 1
            price = int(r["price_pcm"]) if r["price_pcm"] else 0
            available_prices_list.append({
                "name": r["name"],
                "price_pcm": price if price > 0 else None
            })

    # store prices as compact JSON
    available_rooms_prices = json.dumps(available_prices_list, separators=(",", ":"))

    conn.execute("""
        UPDATE houses SET
            ensuites_total = ?,
            available_rooms_total = ?,
            available_rooms_prices = ?,
            double_beds_total = ?,
            suitable_for_couples_total = ?
        WHERE id = ?
    """, (
        ensuites_total,
        available_rooms_total,
        available_rooms_prices,
        double_beds_total,
        suitable_for_couples_total,
        house_id
    ))
    conn.commit()

    return {
        "ensuites_total": ensuites_total,
        "available_rooms_total": available_rooms_total,
        "available_rooms_prices": available_rooms_prices,
        "double_beds_total": double_beds_total,
        "suitable_for_couples_total": suitable_for_couples_total,
    }
