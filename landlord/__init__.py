# admin/__init__.py
from __future__ import annotations

import os
from datetime import datetime as dt, timedelta
from flask import Blueprint, session, current_app, redirect, url_for, render_template, jsonify
import sqlite3

# One shared blueprint so endpoint names stay 'admin.*'
bp = Blueprint("admin", __name__, url_prefix="/admin")

# ---- Shared helpers ----
def _is_admin() -> bool:
    return bool(session.get("is_admin"))

def _admin_token() -> str:
    return (current_app.config.get("ADMIN_TOKEN")
            or os.environ.get("ADMIN_TOKEN", ""))

def require_admin():
    """Redirect to admin login if not authenticated."""
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))
    return None

# ---- DB helpers ----
def _get_conn() -> sqlite3.Connection:
    from db import get_db  # lazy import to avoid circulars
    return get_db()

def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        return int(row["c"]) if row else 0
    except Exception:
        return 0

def _count_since(conn: sqlite3.Connection, table: str, since_iso: str) -> int:
    """
    Counts rows created in the last 24h based on a 'created_at' TEXT ISO column.
    If the table has no created_at, returns 0.
    """
    # check if column exists
    try:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
    except Exception:
        return 0
    if "created_at" not in cols:
        return 0
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE created_at >= ?",
            (since_iso,)
        ).fetchone()
        return int(row["c"]) if row else 0
    except Exception:
        return 0

def _gather_stats() -> dict:
    conn = _get_conn()
    since_iso = (dt.utcnow() - timedelta(hours=24)).isoformat()

    landlords_total = _count(conn, "landlords")
    houses_total    = _count(conn, "houses")
    rooms_total     = _count(conn, "rooms")

    landlords_24h = _count_since(conn, "landlords", since_iso)
    houses_24h    = _count_since(conn, "houses", since_iso)
    rooms_24h     = _count_since(conn, "rooms", since_iso)

    return {
        "since_iso": since_iso,
        "landlords_total": landlords_total,
        "houses_total": houses_total,
        "rooms_total": rooms_total,
        "landlords_24h": landlords_24h,
        "houses_24h": houses_24h,
        "rooms_24h": rooms_24h,
    }

# ---- Routes: INDEX + DASHBOARD + (optional JSON) ----

@bp.route("/")
def admin_index():
    r = require_admin()
    if r:
        return r
    stats = _gather_stats()
    return render_template("admin_index.html", stats=stats)

@bp.route("/dashboard")
def admin_dashboard():
    r = require_admin()
    if r:
        return r
    stats = _gather_stats()
    return render_template("admin_dashboard.html", stats=stats)

# Simple JSON (handy for future charts, but dashboard is server-rendered)
@bp.route("/stats.json")
def admin_stats_json():
    r = require_admin()
    if r:
        return r
    return jsonify(_gather_stats())

# ---- Import the rest of the admin modules LAST to register their routes ----
# Keep only the modules that really exist in your repo to avoid import errors.
from . import auth as _auth            # noqa: F401,E402
from . import cities as _cities        # noqa: F401,E402
from . import landlords as _landlords  # noqa: F401,E402
from . import images as _images        # noqa: F401,E402
# Backups module is optional; import if present
try:
    from . import backups as _backups  # noqa: F401,E402
except Exception:
    pass
