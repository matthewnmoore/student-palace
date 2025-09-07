# utils_summaries.py
from __future__ import annotations
import json
from typing import Dict, Any, Iterable
from sqlite3 import Connection

# Bed sizes that count as "double"
DOUBLE_SIZES = {"Small double", "Double", "King"}


# -------------------------------
# schema helpers (add-only)
# -------------------------------
def _table_info(conn: Connection, table: str) -> list[dict]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # Convert to dicts keyed by name for convenience
    return [dict(zip([c[0] for c in rows.description] if hasattr(rows, "description") else
                     ["cid", "name", "type", "notnull", "dflt_value", "pk"], r)) for r in rows]

def _has_column(conn: Connection, table: str, col: str) -> bool:
    return any(row["name"] == col for row in _table_info(conn, table))

def _safe_add_column(conn: Connection, table: str, ddl: str) -> None:
    """
    Add-only migration: `ddl` should be just the "ADD COLUMN ..." clause.
    Example: _safe_add_column(conn, "houses", "ADD COLUMN ensuites_total INTEGER NOT NULL DEFAULT 0")
    """
    try:
        conn.execute(f"ALTER TABLE {table} {ddl}")
        conn.commit()
    except Exception:
        # If it already exists or ALTER fails for a benign reason, ignore.
        conn.rollback()

def ensure_house_rollup_columns(conn: Connection) -> None:
    """
    Make sure all rollup columns exist on houses (add-only, idempotent).
    """
    # Totals
    if not _has_column(conn, "houses", "ensuites_total"):
        _safe_add_column(conn, "houses", "ADD COLUMN ensuites_total INTEGER NOT NULL DEFAULT 0")
    if not _has_column(conn, "houses", "available_rooms_total"):
        _safe_add_column(conn, "houses", "ADD COLUMN available_rooms_total INTEGER NOT NULL DEFAULT 0")
    if not _has_column(conn, "houses", "available_rooms_prices"):
        _safe_add_column(conn, "houses", "ADD COLUMN available_rooms_prices TEXT NOT NULL DEFAULT '[]'")
    if not _has_column(conn, "houses", "double_beds_total"):
        _safe_add_column(conn, "houses", "ADD COLUMN double_beds_total INTEGER NOT NULL DEFAULT 0")
    if not _has_column(conn, "houses", "suitable_for_couples_total"):
        _safe_add_column(conn, "houses", "ADD COLUMN suitable_for_couples_total INTEGER NOT NULL DEFAULT 0")
    if not _has_column(conn, "houses", "suitable_for_disabled_total"):
        _safe_add_column(conn, "houses", "ADD COLUMN suitable_for_disabled_total INTEGER NOT NULL DEFAULT 0")

    # Available-only
    if not _has_column(conn, "houses", "ensuites_available"):
        _safe_add_column(conn, "houses", "ADD COLUMN ensuites_available INTEGER NOT NULL DEFAULT 0")
    if not _has_column(conn, "houses", "double_beds_available"):
        _safe_add_column(conn, "houses", "ADD COLUMN double_beds_available INTEGER NOT NULL DEFAULT 0")
    if not _has_column(conn, "houses", "couples_ok_available"):
        _safe_add_column(conn, "houses", "ADD COLUMN couples_ok_available INTEGER NOT NULL DEFAULT 0")
    if not _has_column(conn, "houses", "disabled_ok_available"):
        _safe_add_column(conn, "houses", "ADD COLUMN disabled_ok_available INTEGER NOT NULL DEFAULT 0")


# -------------------------------
# recompute logic
# -------------------------------
def _iter_rooms_for_house(conn: Connection, house_id: int) -> Iterable[dict]:
    return conn.execute(
        """
        SELECT
            name,
            COALESCE(ensuite, 0)            AS ensuite,
            COALESCE(is_let, 0)             AS is_let,
            COALESCE(price_pcm, 0)          AS price_pcm,
            TRIM(COALESCE(bed_size, ''))    AS bed_size,
            COALESCE(couples_ok, 0)         AS couples_ok,
            COALESCE(disabled_ok, 0)        AS disabled_ok
        FROM rooms
        WHERE house_id = ?
        """,
        (house_id,)
    ).fetchall()


def recompute_house_summaries(conn: Connection, house_id: int) -> Dict[str, Any]:
    """
    Recalculate and persist **totals** and **available-only** rollups for a house.
    Returns the dict of values written.
    """
    ensure_house_rollup_columns(conn)

    rows = list(_iter_rooms_for_house(conn, house_id))

    # Totals
    ensuites_total = 0
    double_beds_total = 0
    suitable_for_couples_total = 0
    suitable_for_disabled_total = 0

    # Available-only
    available_rooms_total = 0
    ensuites_available = 0
    double_beds_available = 0
    couples_ok_available = 0
    disabled_ok_available = 0

    available_prices_list = []  # list of {"name": str, "price_pcm": int|None}

    for r in rows:
        ensuite = int(r["ensuite"]) == 1
        is_available = int(r["is_let"]) == 0
        bed_size = (r["bed_size"] or "").strip()
        is_double = bed_size in DOUBLE_SIZES
        couples_ok = int(r["couples_ok"]) == 1
        disabled_ok = int(r["disabled_ok"]) == 1

        # Totals
        if ensuite:
            ensuites_total += 1
        if is_double:
            double_beds_total += 1
        if couples_ok:
            suitable_for_couples_total += 1
        if disabled_ok:
            suitable_for_disabled_total += 1

        # Available-only
        if is_available:
            available_rooms_total += 1
            if ensuite:
                ensuites_available += 1
            if is_double:
                double_beds_available += 1
            if couples_ok:
                couples_ok_available += 1
            if disabled_ok:
                disabled_ok_available += 1

            price = int(r["price_pcm"]) if r["price_pcm"] else 0
            available_prices_list.append(
                {"name": r["name"], "price_pcm": price if price > 0 else None}
            )

    available_rooms_prices = json.dumps(available_prices_list, separators=(",", ":"))

    # Persist to houses
    conn.execute(
        """
        UPDATE houses SET
            ensuites_total = ?,
            available_rooms_total = ?,
            available_rooms_prices = ?,
            double_beds_total = ?,
            suitable_for_couples_total = ?,
            suitable_for_disabled_total = ?,
            ensuites_available = ?,
            double_beds_available = ?,
            couples_ok_available = ?,
            disabled_ok_available = ?
        WHERE id = ?
        """,
        (
            ensuites_total,
            available_rooms_total,
            available_rooms_prices,
            double_beds_total,
            suitable_for_couples_total,
            suitable_for_disabled_total,
            ensuites_available,
            double_beds_available,
            couples_ok_available,
            disabled_ok_available,
            house_id,
        ),
    )
    conn.commit()

    return {
        "ensuites_total": ensuites_total,
        "available_rooms_total": available_rooms_total,
        "available_rooms_prices": available_rooms_prices,
        "double_beds_total": double_beds_total,
        "suitable_for_couples_total": suitable_for_couples_total,
        "suitable_for_disabled_total": suitable_for_disabled_total,
        "ensuites_available": ensuites_available,
        "double_beds_available": double_beds_available,
        "couples_ok_available": couples_ok_available,
        "disabled_ok_available": disabled_ok_available,
    }


def recompute_all_houses(conn: Connection) -> int:
    """
    Recalculate rollups for every house. Returns the number of houses processed.
    """
    ensure_house_rollup_columns(conn)
    house_ids = [row[0] for row in conn.execute("SELECT id FROM houses").fetchall()]
    for hid in house_ids:
        recompute_house_summaries(conn, hid)
    return len(house_ids)
