# admin/__init__.py
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
# These come first (existing modules in your project)
from . import auth as _auth            # noqa: F401,E402
from . import cities as _cities        # noqa: F401,E402
from . import landlords as _landlords  # noqa: F401,E402
from . import images as _images        # noqa: F401,E402

# ---- New modules (backup + stats) imported safely to avoid circulars ----
for mod in ("admin.backup", "admin.stats"):
    try:
        importlib.import_module(mod)
    except Exception as e:
        # Don’t crash boot if a file is missing during first deploy; just log.
        print(f"[admin] Optional module '{mod}' not loaded: {e}")
