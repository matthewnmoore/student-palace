from __future__ import annotations

import importlib
from flask import Blueprint, session, redirect, url_for

# One shared blueprint so endpoint names stay 'landlord.*'
bp = Blueprint("landlord", __name__, url_prefix="/landlord")

# ---- Shared helpers (importable by submodules) ----
def _is_landlord() -> bool:
    # We assume your auth sets session["landlord_id"] when logged in
    return bool(session.get("landlord_id"))

def require_landlord():
    """Redirect to landlord login if not authenticated."""
    if not _is_landlord():
        return redirect(url_for("auth.login"))  # adjust if your login endpoint differs
    return None

# ---- Import routes so their decorators register on bp ----
# Keep these imports at the end to avoid circular imports.
from . import dashboard as _dashboard  # noqa: F401,E402
from . import houses as _houses        # noqa: F401,E402
from . import photos as _photos        # noqa: F401,E402
from . import rooms as _rooms          # noqa: F401,E402
from . import profile as _profile      # noqa: F401,E402
from . import epc as _epc              # NEW: EPC upload routes  # noqa: F401,E402

# Optionally import any extra landlord modules if present (non-fatal if missing)
for _mod in ("helpers",):
    try:
        importlib.import_module(f"landlord.{_mod}")
    except Exception:
        pass
