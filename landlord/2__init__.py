# landlord/__init__.py
from __future__ import annotations
from flask import Blueprint

# Shared blueprint so endpoint names stay 'landlord.*'
bp = Blueprint("landlord", __name__, url_prefix="/landlord")

# Explicit imports so their @bp.route decorators register.
from . import dashboard as _dashboard      # noqa: F401,E402
from . import houses as _houses            # noqa: F401,E402
from . import photos as _photos            # noqa: F401,E402
from . import floorplans as _floorplans    # noqa: F401,E402
from . import room_photos as _room_photos  # noqa: F401,E402
from . import profile as _profile          # noqa: F401,E402
from . import rooms as _rooms              # noqa: F401,E402
from . import epc as _epc                  # noqa: F401,E402
from . import rooms_all as _rooms_all      # noqa: F401,E402
from . import bulk as _bulk                # noqa: F401,E402
from . import rooms_all_edit as _rooms_all_edit  # noqa: F401,E402
from . import portfolio as _portfolio      # noqa: F401,E402
from . import delete as _delete            # noqa: F401,E402
