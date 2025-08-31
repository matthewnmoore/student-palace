# landlord/__init__.py
from __future__ import annotations

import os
import importlib
from flask import Blueprint, session, current_app, redirect, url_for

# One shared blueprint so endpoint names stay 'landlord.*'
bp = Blueprint("landlord", __name__, url_prefix="/landlord")

# ---- Shared helpers (importable by submodules) ----
def _is_landlord() -> bool:
    return bool(session.get("landlord_id"))

def require_landlord():
    """Redirect to landlord entry/login if not authenticated."""
    if not _is_landlord():
        return redirect(url_for("auth.landlords_entry"))
    return None

def _config(key: str, default: str = "") -> str:
    return (current_app.config.get(key) or os.environ.get(key, default))

# ---- Import routes so their decorators register on bp ----
# Use lazy imports to avoid circular import crashes.
for mod in (
    "landlord.auth",        # login/logout, entry routes
    "landlord.houses",      # list/create/edit houses
    "landlord.rooms",       # manage rooms
    "landlord.photos",      # photo upload/delete/primary
):
    try:
        importlib.import_module(mod)
    except ModuleNotFoundError:
        # If some modules don’t exist in your repo, it’s fine to skip them.
        pass
