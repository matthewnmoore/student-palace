# landlord/__init__.py
from __future__ import annotations

import importlib
from flask import Blueprint, session, redirect, url_for

# One shared blueprint for all landlord routes
bp = Blueprint("landlord", __name__, url_prefix="/landlord")

# ---- Shared helpers (importable by submodules) ----
def _is_landlord() -> bool:
    return bool(session.get("landlord_id"))

def require_landlord():
    """Redirect to landlord login if not authenticated."""
    if not _is_landlord():
        return redirect(url_for("landlord.landlord_login"))
    return None

# ---- Import submodules *after* bp is defined to avoid circular imports ----
# Only import modules that actually exist in your repo. Safe-import pattern prevents crashes.
for _mod in (
    "auth",        # e.g. login/logout
    "houses",      # list/create/edit houses
    "rooms",       # room management
    "photos",      # uploads & gallery
    "views",       # any other landlord views
):
    try:
        importlib.import_module(f"{__name__}.{_mod}")
    except ModuleNotFoundError:
        # Skip silently if the file doesn't exist; keeps deploys resilient
        pass
