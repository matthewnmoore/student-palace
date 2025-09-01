# landlord/__init__.py
from __future__ import annotations

from flask import Blueprint

# Shared blueprint so endpoint names stay 'landlord.*'
bp = Blueprint("landlord", __name__)

# Explicit imports so their @bp.route decorators register.
from . import dashboard as _dashboard      # noqa: F401,E402
from . import houses as _houses            # noqa: F401,E402
from . import photos as _photos            # noqa: F401,E402
from . import floorplans as _floorplans    # ← NEW: Floor plans routes  # noqa: F401,E402
from . import room_photos as _room_photos  # noqa: F401,E402
from . import profile as _profile          # noqa: F401,E402
from . import rooms as _rooms              # noqa: F401,E402
from . import epc as _epc                  # ← NEW: EPC routes














