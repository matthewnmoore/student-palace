from flask import Blueprint

# Single shared blueprint for all landlord routes
landlord_bp = Blueprint("landlord", __name__, url_prefix="")

# Import submodules so they register routes on the same blueprint.
# NOTE: keep these imports at the end to avoid circular imports.
from . import core  # noqa: E402,F401
from . import photos  # noqa: E402,F401
