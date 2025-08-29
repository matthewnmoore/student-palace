# admin/__init__.py
from __future__ import annotations

import os
from flask import Blueprint, session, current_app

# One shared blueprint so endpoint names stay 'admin.*'
bp = Blueprint("admin", __name__, url_prefix="/admin")

# ---- Shared helpers (importable by submodules) ----
def _is_admin() -> bool:
    return bool(session.get("is_admin"))

def _admin_token() -> str:
    return (
        current_app.config.get("ADMIN_TOKEN")
        or os.environ.get("ADMIN_TOKEN", "")
    )

# ---- Import submodules to register their routes ----
# These imports must come after `bp` is defined
from . import auth, cities, landlords
