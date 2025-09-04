# utils_summaries.py
from __future__ import annotations
import json
from typing import Dict, Any
from sqlite3 import Connection

# Treat these bed sizes as "double" for the rollups
DOUBLE_SIZES = {"Small double", "Double", "King"}


# ---------- add-only migration helpers (safe to call repeatedly) ----------
def _table_cols(conn: Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] if isinstance(r, dict) else r[1] for r in rows}

def _safe_add_column(conn: Connection, table: str, ddl_fragment: str) -> None:
    """
    Add a column to `table` if it does not already exist.
    ddl_fragment should be like: `ADD COLUMN my_col INTEGER NOT NULL DEFAULT 0`
    """
    # Extract column name after 'ADD COLUMN '
    frag = ddl_fragment.strip()
    target = frag.upper().split("ADD COLUMN", 1)[1].strip()
    col_name = target.split()[0]
    existing = _table_cols(conn, table)
    if col_name not in existing:
        conn.execute(f"ALTER TABLE {table} {ddl_fragment}")

def _ensure_house_rollup_columns(conn: Connection) -> None:
    """
    Make sure all rollup columns exist on houses (add-only, no drops).
    """
    # Existing (but ensure anyway in case of older db): totals + available rooms + prices
    _safe_add_column(conn, "houses", "ADD COLUMN ensuites_total INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN double_beds_total INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN suitable_for_couples_total INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN available_rooms_total INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN available_rooms_prices TEXT NOT NULL DEFAULT '[]'")

    # New: available variants (these are the ones your admin check page needs)
    _safe_add_column(conn, "houses", "ADD COLUMN ensuites_available INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN double_beds_available INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN couples_ok_available INTEGER NOT NULL DEFAULT 0")
# --------------------------------------------------------------------------


def recompute_house_summaries(conn: Connection, house_id: int) -> Dict[str, Any]:
    """
    Recalculate and persist summary fields on houses for the given house_id.
    Returns the dict of values written.
    """
    # Ensure schema supports all fields we’re going to write
    _ensure_house_rollup_columns(conn)

    rows = conn.execute("""
        SELECT
            name,
            COALESCE(ensuite,0)    AS ensuite,
            COALESCE(is_let,0)     AS is_let,
            COALESCE(price_pcm,0)  AS price_pcm,
            TRIM(COALESCE(bed_size,'')) AS bed_size,
            COALESCE(couples_ok,0) AS couples_ok
        FROM rooms
        WHERE house_id=?
    """, (house_id,)).fetchall()

    # Totals (all rooms regardless of let status)
    ensuites_total = 0
    double_beds_total = 0
    suitable_for_couples_total = 0

    # Availability (only rooms where is_let == 0)
    available_rooms_total = 0
    ensuites_available = 0
    double_beds_available = 0
    couples_ok_available = 0

    # Price summary for *available* rooms only
    available_prices_list = []   # list of dicts: {"name": "...", "price_pcm": 999}

    for r in rows:
        ensuite = int(r["ensuite"]) == 1
        is_let = int(r["is_let"]) == 1
        couples_ok = int(r["couples_ok"]) == 1
        bed_size = (r["bed_size"] or "")
        is_double = bed_size in DOUBLE_SIZES

        # Totals across all rooms
        if ensuite:
            ensuites_total += 1
        if is_double:
            double_beds_total += 1
        if couples_ok:
            suitable_for_couples_total += 1

        # Available-only rollups
        if not is_let:
            available_rooms_total += 1
            if ensuite:
                ensuites_available += 1
            if is_double:
                double_beds_available += 1
            if couples_ok:
                couples_ok_available += 1

            # Include price if positive, else null
            try:
                price = int(r["price_pcm"]) if r["price_pcm"] is not None else 0
            except Exception:
                price = 0
            available_prices_list.append({
                "name": r["name"],
                "price_pcm": price if price > 0 else None
            })

    # Store prices as compact JSON
    available_rooms_prices = json.dumps(available_prices_list, separators=(",", ":"))

    # Persist to houses
    conn.execute("""
        UPDATE houses SET
            ensuites_total = ?,
            double_beds_total = ?,
            suitable_for_couples_total = ?,

            available_rooms_total = ?,
            available_rooms_prices = ?,

            ensuites_available = ?,
            double_beds_available = ?,
            couples_ok_available = ?
        WHERE id = ?
    """, (
        ensuites_total,
        double_beds_total,
        suitable_for_couples_total,

        available_rooms_total,
        available_rooms_prices,

        ensuites_available,
        double_beds_available,
        couples_ok_available,
        house_id
    ))
    conn.commit()

    return {
        "ensuites_total": ensuites_total,
        "double_beds_total": double_beds_total,
        "suitable_for_couples_total": suitable_for_couples_total,
        "available_rooms_total": available_rooms_total,
        "available_rooms_prices": available_rooms_prices,
        "ensuites_available": ensuites_available,
        "double_beds_available": double_beds_available,
        "couples_ok_available": couples_ok_available,
    }


def recompute_all_houses(conn: Connection) -> None:
    """
    Recompute summaries for every house (used by Admin → Recompute all).
    """
    _ensure_house_rollup_columns(conn)
    ids = conn.execute("SELECT id FROM houses").fetchall()
    for row in ids:
        hid = row["id"] if isinstance(row, dict) else row[0]
        recompute_house_summaries(conn, hid)
