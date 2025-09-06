# admin/stats.py
from __future__ import annotations

from datetime import datetime, timedelta
from flask import render_template
from db import get_db
from . import bp, require_admin


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


# ---- Photos helpers: house_images + room_images ----
def _count_photos(conn) -> int:
    return _count(conn, "house_images") + _count(conn, "room_images")


def _count_photos_since(conn, cutoff_iso: str) -> int:
    return (
        _count_since(conn, "house_images", cutoff_iso)
        + _count_since(conn, "room_images", cutoff_iso)
    )


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
        "photos":    _count_photos(conn),
    }

    # Period cutoffs
    now = datetime.utcnow()
    periods = {
        "24h":  now - timedelta(days=1),
        "7d":   now - timedelta(days=7),
        "30d":  now - timedelta(days=30),
        "365d": now - timedelta(days=365),
    }
    cutoffs = {k: v.isoformat() for k, v in periods.items()}

    # Deltas per period
    deltas = {k: {} for k in periods.keys()}
    for period_key, cutoff_iso in cutoffs.items():
        deltas[period_key]["landlords"] = _count_since(conn, "landlords", cutoff_iso)
        deltas[period_key]["houses"]    = _count_since(conn, "houses", cutoff_iso)
        deltas[period_key]["rooms"]     = _count_since(conn, "rooms", cutoff_iso)
        deltas[period_key]["photos"]    = _count_photos_since(conn, cutoff_iso)

    conn.close()

    return render_template(
        "admin_dashboard.html",
        totals=totals,
        deltas=deltas,
    )
