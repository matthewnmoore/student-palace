# landlord/helpers.py

from datetime import date
from typing import Tuple, Dict, List
from flask import Request

def _clean_int(v: str, default: int = 0) -> int:
    try:
        if v is None:
            return default
        v = str(v).replace(",", "").strip()
        if v == "":
            return default
        return max(0, int(float(v)))
    except Exception:
        return default

def _clean_text(v: str) -> str:
    return (v or "").strip()

def _clean_iso_date(v: str) -> str:
    """
    Accepts 'YYYY-MM-DD' and returns the same, or '' if invalid/empty.
    Uses date.fromisoformat (no timezone, no midnight conversion).
    """
    s = (v or "").strip()
    if not s:
        return ""
    try:
        d = date.fromisoformat(s)
        return d.isoformat()  # 'YYYY-MM-DD'
    except Exception:
        return ""

def _checkbox_raw(request: Request, name: str) -> int:
    """
    Light checkbox read (rooms.py will overwrite for certain fields anyway).
    Keep this tolerant so form preview doesn’t break.
    """
    vals = [str(v).strip().lower() for v in request.form.getlist(name)]
    return 1 if ("1" in vals or "on" in vals or "true" in vals) else 0

def room_form_values(request: Request) -> Tuple[Dict[str, object], List[str]]:
    """
    Build the values dict for a room form without doing any timezone math.
    Dates remain pure 'YYYY-MM-DD' strings.
    """
    errors: List[str] = []

    name = _clean_text(request.form.get("name"))
    if not name:
        errors.append("Please enter a room name.")

    bed_size = _clean_text(request.form.get("bed_size"))
    if not bed_size:
        errors.append("Please choose a bed size.")

    vals: Dict[str, object] = {
        # Basics
        "name": name,
        "room_size": _clean_text(request.form.get("room_size")),
        "bed_size": bed_size,
        "price_pcm": _clean_int(request.form.get("price_pcm"), 0),

        # Description
        "description": _clean_text(request.form.get("description")),

        # Feature checkboxes
        "ensuite":         _checkbox_raw(request, "ensuite"),
        "tv":              _checkbox_raw(request, "tv"),
        "desk_chair":      _checkbox_raw(request, "desk_chair"),
        "wardrobe":        _checkbox_raw(request, "wardrobe"),
        "chest_drawers":   _checkbox_raw(request, "chest_drawers"),
        "lockable_door":   _checkbox_raw(request, "lockable_door"),
        "wired_internet":  _checkbox_raw(request, "wired_internet"),
        "safe":            _checkbox_raw(request, "safe"),
        "dressing_table":  _checkbox_raw(request, "dressing_table"),
        "mirror":          _checkbox_raw(request, "mirror"),
        "bedside_table":   _checkbox_raw(request, "bedside_table"),
        "blinds":          _checkbox_raw(request, "blinds"),
        "curtains":        _checkbox_raw(request, "curtains"),
        "sofa":            _checkbox_raw(request, "sofa"),

        # Availability (parsed as DATE ONLY)
        "is_let":         _checkbox_raw(request, "is_let"),
        "let_until":      _clean_iso_date(request.form.get("let_until")),
        "available_from": _clean_iso_date(request.form.get("available_from")),
        
        # Couples/disabled (rooms.py will overwrite, but keep here for completeness)
        "couples_ok":     _checkbox_raw(request, "couples_ok"),
        "disabled_ok":    _checkbox_raw(request, "disabled_ok"),
    }

    # If the user typed an invalid date, surface a gentle error (optional)
    raw_lu = (request.form.get("let_until") or "").strip()
    if raw_lu and not vals["let_until"]:
        errors.append("‘Let until’ must be a valid date (YYYY-MM-DD).")

    raw_af = (request.form.get("available_from") or "").strip()
    if raw_af and not vals["available_from"]:
        errors.append("‘Available from’ must be a valid date (YYYY-MM-DD).")

    return vals, errors
