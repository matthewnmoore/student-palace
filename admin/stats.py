# admin/stats.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from flask import render_template

from . import bp, require_admin
from db import get_db

@bp.route("/")
def admin_index():
    need = require_admin()
    if need:
        return need

    conn = get_db()

    totals = {
        "landlords": _count(conn, "SELECT COUNT(*) FROM landlords"),
        "houses":    _count(conn, "SELECT COUNT(*) FROM houses"),
        "rooms":     _count(conn, "SELECT COUNT(*) FROM rooms"),
    }

    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    deltas = {
        "landlords": _count(conn, "SELECT COUNT(*) FROM landlords WHERE created_at >= ?", (since,)),
        "houses":    _count(conn, "SELECT COUNT(*) FROM houses    WHERE created_at >= ?", (since,)),
        "rooms":     _count(conn, "SELECT COUNT(*) FROM rooms     WHERE created_at >= ?", (since,)),
    }

    return render_template("admin_index.html", totals=totals, deltas=deltas)

def _count(conn, sql: str, params: tuple = ()):
    try:
        return int(conn.execute(sql, params).fetchone()[0])
    except Exception:
        return 0
