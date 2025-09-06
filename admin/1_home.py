# admin/home.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from flask import render_template, redirect, url_for
import sqlite3
from db import get_db
from . import bp, _is_admin

def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        return int(row["c"] if row else 0)
    except Exception:
        return 0

def _count_since(conn: sqlite3.Connection, table: str, cutoff_iso: str) -> int:
    # Only works if table has created_at (safe-guarded)
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "created_at" not in cols:
            return 0
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE created_at >= ?",
            (cutoff_iso,),
        ).fetchone()
        return int(row["c"] if row else 0)
    except Exception:
        return 0

@bp.route("/", methods=["GET"])
def admin_index():
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_db()
    try:
        # 24h cutoff (UTC ISO without tz so it matches your stored strings)
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None).isoformat()

        totals = {
            "landlords": _count(conn, "landlords"),
            "houses":    _count(conn, "houses"),
            "rooms":     _count(conn, "rooms"),
            "photos":    _count(conn, "house_images"),
        }
        deltas = {
            "landlords": _count_since(conn, "landlords", cutoff_iso),
            "houses":    _count_since(conn, "houses", cutoff_iso),
            "rooms":     _count_since(conn, "rooms", cutoff_iso),
            "photos":    _count_since(conn, "house_images", cutoff_iso),
        }
        # keep your older “stats” block for backwards compatibility
        stats = {
            "landlords_total": totals["landlords"],
            "houses_total":    totals["houses"],
            "rooms_total":     totals["rooms"],
            "photos_total":    totals["photos"],
            "landlords_24h":   deltas["landlords"],
            "houses_24h":      deltas["houses"],
            "rooms_24h":       deltas["rooms"],
            "photos_24h":      deltas["photos"],
        }

        return render_template("admin_index.html", totals=totals, deltas=deltas, stats=stats)
    finally:
        conn.close()
