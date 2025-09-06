# admin/stats.py
from __future__ import annotations

from datetime import datetime, timedelta
from flask import render_template
from db import get_db
from . import bp, require_admin

TABLES = ("landlords", "houses", "rooms", "house_images")  # house_images = photos

def _count(conn, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        return int(row["c"] if row else 0)
    except Exception:
        return 0

def _has_column(conn, table: str, col: str) -> bool:
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return col in cols
    except Exception:
        return False

def _count_since(conn, table: str, cutoff_iso: str) -> int:
    # Only count when a created_at column exists
    if not _has_column(conn, table, "created_at"):
        return 0
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE created_at >= ?",
            (cutoff_iso,),
        ).fetchone()
        return int(row["c"] if row else 0)
    except Exception:
        return 0

@bp.get("/dashboard", endpoint="dashboard")
def admin_dashboard():
    """Read-only stats dashboard at /admin/dashboard."""
    r = require_admin()
    if r:
        return r

    conn = get_db()

    # Totals
    totals = {
        "landlords": _count(conn, "landlords"),
        "houses":    _count(conn, "houses"),
        "rooms":     _count(conn, "rooms"),
        "photos":    _count(conn, "house_images"),
    }

    # Period cutoffs
    now = datetime.utcnow()
    periods = {
        "24h":  now - timedelta(days=1),
        "7d":   now - timedelta(days=7),
        "30d":  now - timedelta(days=30),
        "365d": now - timedelta(days=365),
    }
    # Convert to ISO strings (no tz to match stored values)
    cutoffs = {k: v.isoformat() for k, v in periods.items()}

    # Deltas per period
    deltas = {k: {} for k in periods.keys()}
    # Mapping for display names to tables
    tbl_map = {
        "landlords": "landlords",
        "houses":    "houses",
        "rooms":     "rooms",
        "photos":    "house_images",
    }
    for period_key, cutoff_iso in cutoffs.items():
        for display_key, table in tbl_map.items():
            deltas[period_key][display_key] = _count_since(conn, table, cutoff_iso)

    conn.close()

    return render_template(
        "admin_dashboard.html",
        totals=totals,
        deltas=deltas,
    )
