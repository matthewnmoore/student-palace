from flask import Blueprint

# One shared blueprint so endpoint names stay as 'landlord.*'
bp = Blueprint("landlord", __name__, url_prefix="")

# Import submodules so their routes attach to this bp
from . import dashboard, profile, houses, rooms  # noqa: E402,F401
