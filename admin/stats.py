# admin/stats.py
from __future__ import annotations

from datetime import datetime, timedelta
from flask import render_template
from db import get_db
from . import bp, require_admin


@bp.get("/dashboard", endpoint="dashboard")
def admin_dashboard():
    """Read-only stats dashboard at /admin/dashboard."""
    r = require_admin()
    if r:
        return r

    conn = get_db()

    # Total counts
    totals = {}
    for t in ("landlords", "houses", "rooms"):
        try:
            totals[t] = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
        except Exception:
            totals[t] = "n/a"

    # 24h deltas (uses created_at on each table)
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    deltas = {}
    for t in ("landlords", "houses", "rooms"):
        try:
            deltas[t] = conn.execute(
                f"SELECT COUNT(*) AS c FROM {t} WHERE created_at >= ?",
                (cutoff,),
            ).fetchone()["c"]
        except Exception:
            deltas[t] = "n/a"

    conn.close()

    return render_template(
        "admin_dashboard.html",
        totals=totals,
        deltas=deltas,
    )
