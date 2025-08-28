# landlord/__init__.py
from flask import Blueprint

# One shared blueprint so endpoint names stay as 'landlord.*'
bp = Blueprint("landlord", __name__, url_prefix="")

# Import submodules so their routes attach to this bp
# (Order doesn't really matter, but keeping a tidy grouping helps.)
from . import dashboard   # noqa: E402,F401
from . import profile     # noqa: E402,F401
from . import houses      # noqa: E402,F401
from . import rooms       # noqa: E402,F401
from . import photos      # noqa: E402,F401
