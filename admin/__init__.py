# admin/__init__.py
from __future__ import annotations

import os
from datetime import datetime, timedelta
from flask import Blueprint, session, current_app, redirect, url_for, render_template
from db import get_db  # ✅ need this for stats

bp = Blueprint("admin", __name__, url_prefix="/admin")

# ---- Shared helpers (importable by submodules) ----
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

# ---- Dashboard ----
@bp.route("/")
def admin_dashboard():
    # ensure logged in
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_db()
    c = conn.cursor()

    stats = {}

    # Totals
    stats["landlords_total"] = c.execute("SELECT COUNT(*) FROM landlords").fetchone()[0]
    stats["houses_total"] = c.execute("SELECT COUNT(*) FROM houses").fetchone()[0]
    stats["rooms_total"] = c.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]

    # 24h cut-off
    since = (datetime.utcnow() - timedelta(days=1)).isoformat()

    stats["landlords_24h"] = c.execute(
        "SELECT COUNT(*) FROM landlords WHERE created_at >= ?", (since,)
    ).fetchone()[0]

    stats["houses_24h"] = c.execute(
        "SELECT COUNT(*) FROM houses WHERE created_at >= ?", (since,)
    ).fetchone()[0]

    stats["rooms_24h"] = c.execute(
        "SELECT COUNT(*) FROM rooms WHERE created_at >= ?", (since,)
    ).fetchone()[0]

    conn.close()

    return render_template("admin_index.html", stats=stats)

# ---- Import routes so their decorators register on bp ----
from . import auth as _auth        # noqa: F401,E402
from . import cities as _cities    # noqa: F401,E402
from . import landlords as _landlords  # noqa: F401,E402
from . import images as _images    # noqa: F401,E402
from . import backup as _backup    # ✅ if you created admin_backup
