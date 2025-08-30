# admin/stats.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from flask import render_template
from db import get_db
from . import bp, require_admin

@bp.route("/dashboard", endpoint="dashboard")
def admin_dashboard():
    r = require_admin()
    if r:
        return r

    conn = get_db()

    # current totals
    landlords_total = conn.execute("SELECT COUNT(*) AS c FROM landlords").fetchone()["c"]
    houses_total    = conn.execute("SELECT COUNT(*) AS c FROM houses").fetchone()["c"]
    rooms_total     = conn.execute("SELECT COUNT(*) AS c FROM rooms").fetchone()["c"]

    # last 24 hours (UTC)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")

    landlords_24h = conn.execute(
        "SELECT COUNT(*) AS c FROM landlords WHERE created_at >= ?", (cutoff,)
    ).fetchone()["c"]

    houses_24h = conn.execute(
        "SELECT COUNT(*) AS c FROM houses WHERE created_at >= ?", (cutoff,)
    ).fetchone()["c"]

    rooms_24h = conn.execute(
        "SELECT COUNT(*) AS c FROM rooms WHERE created_at >= ?", (cutoff,)
    ).fetchone()["c"]

    stats = {
        "landlords_total": landlords_total, "landlords_24h": landlords_24h,
        "houses_total": houses_total, "houses_24h": houses_24h,
        "rooms_total": rooms_total, "rooms_24h": rooms_24h,
    }

    return render_template("admin_dashboard.html", stats=stats)
