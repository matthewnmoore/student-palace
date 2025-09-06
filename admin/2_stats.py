# admin/stats.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from flask import render_template
import sqlite3
from db import get_db
from . import bp, require_admin


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        return int(row["c"] if row else 0)
    except Exception:
        return 0


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return col in cols
    except Exception:
        return False


def _count_since(conn: sqlite3.Connection, table: str, cutoff_iso: str) -> int:
    # Only if the table has a created_at column
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
    try:
        # Use UTC and store as naive ISO to match your DB style
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).replace(tzinfo=None).isoformat()

        # Totals
        totals = {
            "landlords": _count(conn, "landlords"),
            "houses":    _count(conn, "houses"),
            "rooms":     _count(conn, "rooms"),
            "photos":    _count(conn, "house_images"),
        }

        # Deltas in last 24h
        deltas = {
            "landlords": _count_since(conn, "landlords", cutoff_iso),
            "houses":    _count_since(conn, "houses", cutoff_iso),
            "rooms":     _count_since(conn, "rooms", cutoff_iso),
            "photos":    _count_since(conn, "house_images", cutoff_iso),
        }

        return render_template("admin_dashboard.html", totals=totals, deltas=deltas)
    finally:
        try:
            conn.close()
        except Exception:
            pass
