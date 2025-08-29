# models.py
from __future__ import annotations

import sqlite3
from typing import List
from db import get_db


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if a table has the given column name."""
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return any(r["name"] == column for r in cur.fetchall())
    except Exception:
        return False


def get_active_cities_safe(order_by_admin: bool = True):
    """
    Returns a list of active city rows (sqlite3.Row).
    If cities.sort_order exists and order_by_admin=True, order by sort_order then name.
    Otherwise, order by name.
    On any DB error, returns [] (safe for templates).
    """
    conn = None
    try:
        conn = get_db()
        order_clause = "ORDER BY name ASC"
        if order_by_admin and _table_has_column(conn, "cities", "sort_order"):
            order_clause = "ORDER BY sort_order ASC, name ASC"
        rows = conn.execute(
            f"SELECT * FROM cities WHERE is_active=1 {order_clause}"
        ).fetchall()
        return rows
    except Exception as e:
        print("[WARN] get_active_cities_safe:", e)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_active_city_names(order_by_admin: bool = True) -> List[str]:
    """Convenience helper: returns just the active city names."""
    return [r["name"] for r in get_active_cities_safe(order_by_admin=order_by_admin)]


def validate_city_active(city: str) -> bool:
    """True if the given city exists and is marked active."""
    if not city:
        return False
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT 1 FROM cities WHERE name=? AND is_active=1",
            (city,)
        ).fetchone()
        return bool(row)
    except Exception:
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
