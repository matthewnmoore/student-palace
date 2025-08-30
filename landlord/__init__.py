# admin/__init__.py
from __future__ import annotations

import os
import importlib
from datetime import datetime as dt, timedelta
from flask import Blueprint, session, current_app, redirect, url_for, render_template

# One shared blueprint so endpoint names stay 'admin.*'
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

# ---- Admin Home (now passes stats to the template) ----
@bp.route("/", endpoint="admin_index")
def admin_index():
    r = require_admin()
    if r:
        return r

    try:
        from db import get_db
        conn = get_db()

        def cnt(sql: str, params: tuple = ()) -> int:
            try:
                row = conn.execute(sql, params).fetchone()
                return int(row["c"]) if row else 0
            except Exception:
                return 0

        cutoff_iso = (dt.utcnow() - timedelta(days=1)).isoformat()

        stats = {
            "landlords_total": cnt("SELECT COUNT(*) AS c FROM landlords"),
            "houses_total":    cnt("SELECT COUNT(*) AS c FROM houses"),
            "rooms_total":     cnt("SELECT COUNT(*) AS c FROM rooms"),
            "landlords_24h":   cnt("SELECT COUNT(*) AS c FROM landlords WHERE created_at >= ?", (cutoff_iso,)),
            "houses_24h":      cnt("SELECT COUNT(*) AS c FROM houses    WHERE created_at >= ?", (cutoff_iso,)),
            "rooms_24h":       cnt("SELECT COUNT(*) AS c FROM rooms     WHERE created_at >= ?", (cutoff_iso,)),
        }
    except Exception:
        stats = {
            "landlords_total": 0, "houses_total": 0, "rooms_total": 0,
            "landlords_24h": 0, "houses_24h": 0, "rooms_24h": 0,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return render_template("admin_index.html", stats=stats)

# ---- Import routes so their decorators register on bp ----
# These must come last to avoid circular imports.
# (Use importlib so missing optional modules won’t crash boot.)
try:
    from . import auth as _auth        # noqa: F401
except Exception:
    pass

try:
    from . import cities as _cities    # noqa: F401
except Exception:
    pass

try:
    from . import landlords as _landlords  # noqa: F401
except Exception:
    pass

try:
    from . import images as _images    # noqa: F401
except Exception:
    pass

# Optional extras (only if these files exist)
for _mod in ("backups", "stats"):
    try:
        importlib.import_module(f"admin.{_mod}")
    except Exception:
        pass
