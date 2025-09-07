# landlord/__init__.py
from __future__ import annotations
from flask import Blueprint

# One shared blueprint; routes will attach to this from submodules.
bp = Blueprint("landlord", __name__, url_prefix="/landlord")
