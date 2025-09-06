
from __future__ import annotations

import os
import importlib
from flask import Blueprint, session, current_app, redirect, url_for

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

# ---- Import routes so their decorators register on bp ----
# Keep these core ones explicit (they exist in your repo)
from . import auth as _auth            # noqa: F401,E402
from . import cities as _cities        # noqa: F401,E402
from . import landlords as _landlords  # noqa: F401,E402
from . import images as _images        # noqa: F401,E402
from . import summaries as _summaries  # ✅ NEW: register /admin/summaries routes  # noqa: F401,E402
from . import accreditations as _accreditations  # registers /admin/accreditations






# ---- Import optional modules if present (avoid hard dependency/circulars) ----
# If any of these files aren't present or raise during import, we skip them.
for _mod in ("dashboard", "backup", "backups", "stats"):
    try:
        importlib.import_module(f"admin.{_mod}")
    except Exception:
        # Safe to ignore missing or import-time errors here to prevent circulars
        pass
