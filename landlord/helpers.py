# landlord/helpers.py
from __future__ import annotations

from datetime import datetime as dt, date, timedelta
from typing import Tuple, Dict, Any
from flask import Request

from utils import clean_bool

ISO_FMT = "%Y-%m-%d"

def _parse_uk_date(value: str) -> str:
    """
    Accepts 'DD/MM/YYYY' (UK) or 'YYYY-MM-DD' (HTML date input) and returns ISO 'YYYY-MM-DD'.
    Returns '' if empty or invalid.
    """
    s = (value or "").strip()
    if not s:
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = dt.strptime(s, fmt).date()
            return d.isoformat()
        except Exception:
            continue
    return ""

def _next_year_june_30(today: date | None = None) -> str:
    """Return 30 June of the NEXT calendar year (ISO)."""
    if today is None:
        today = dt.utcnow().date()
    return date(today.year + 1, 6, 30).isoformat()

def room_form_values(request: Request) -> Tuple[Dict[str, Any], list[str]]:
    """
    Parse & normalize room form values.

    Date rules (server-side, tolerant):
      - If is_let == 0 (available): clear let_until; keep available_from as-is (optional).
      - If is_let == 1 (let):
          * if let_until missing -> default to 30 June next year.
          * if available_from present and <= let_until -> bump to day after let_until.
    We DO NOT block saving because of date formats/order; we normalize instead.
    """
    f = request.form
    errors: list[str] = []

    # Basics
    name = (f.get("name") or "").strip()
    if not name:
        errors.append("Room name is required.")
    if len(name) > 20:
        errors.append("Room name cannot be longer than 20 characters.")

    description = (f.get("description") or "").strip()
    if len(description) > 1200:
        errors.append("Room description cannot be longer than 1200 characters.")

    bed_size = (f.get("bed_size") or "").strip()
    if bed_size not in ("Single", "Small double", "Double", "King"):
        errors.append("Please choose a valid bed size.")

    # Numeric
    raw_price = (f.get("price_pcm") or "").strip()
    try:
        price_pcm = int(raw_price.replace(",", ""))
    except Exception:
        price_pcm = 0

    room_size = (f.get("room_size") or "").strip()

    # Booleans
    ensuite         = clean_bool("ensuite")
    tv              = clean_bool("tv")
    desk_chair      = clean_bool("desk_chair")
    wardrobe        = clean_bool("wardrobe")
    chest_drawers   = clean_bool("chest_drawers")
    lockable_door   = clean_bool("lockable_door")
    wired_internet  = clean_bool("wired_internet")
    safe            = clean_bool("safe")
    dressing_table  = clean_bool("dressing_table")
    mirror          = clean_bool("mirror")
    bedside_table   = clean_bool("bedside_table")
    blinds          = clean_bool("blinds")
    curtains        = clean_bool("curtains")
    sofa            = clean_bool("sofa")
    couples_ok      = clean_bool("couples_ok")
    disabled_ok     = clean_bool("disabled_ok")
    is_let          = clean_bool("is_let")

    # Dates (optional, tolerant)
    available_from_in = (f.get("available_from") or "").strip()
    let_until_in      = (f.get("let_until") or "").strip()

    available_from = _parse_uk_date(available_from_in)
    let_until      = _parse_uk_date(let_until_in)

    # Normalize dates based on is_let
    if is_let == 0:
        # Available now: clear let_until regardless of what the browser submitted
        let_until = ""
        # available_from can be left blank or provided; both are fine
    else:
        # Currently let
        if not let_until:
            let_until = _next_year_june_30()
        if available_from:
            try:
                af = dt.strptime(available_from, ISO_FMT).date()
                lu = dt.strptime(let_until, ISO_FMT).date()
                if af <= lu:
                    available_from = (lu + timedelta(days=1)).isoformat()
            except Exception:
                # If parsing fails, just clear available_from to avoid blocking saves
                available_from = ""

    vals: Dict[str, Any] = {
        "name": name,
        "description": description,

        "ensuite": ensuite,
        "bed_size": bed_size,
        "tv": tv,
        "desk_chair": desk_chair,
        "wardrobe": wardrobe,
        "chest_drawers": chest_drawers,
        "lockable_door": lockable_door,
        "wired_internet": wired_internet,
        "room_size": room_size,

        "price_pcm": price_pcm,
        "safe": safe,
        "dressing_table": dressing_table,
        "mirror": mirror,
        "bedside_table": bedside_table,
        "blinds": blinds,
        "curtains": curtains,
        "sofa": sofa,

        "couples_ok": couples_ok,
        "disabled_ok": disabled_ok,

        "is_let": is_let,
        "available_from": available_from,
        "let_until": let_until,
    }

    # Only real input problems (e.g., missing name / invalid bed size) stay as errors.
    return vals, errors

def room_counts(conn, hid):
    """Return (max_rooms, current_count) for a given house."""
    row = conn.execute(
        "SELECT bedrooms_total FROM houses WHERE id=?",
        (hid,)
    ).fetchone()
    max_rooms = int(row["bedrooms_total"]) if row else 0
    cnt = conn.execute(
        "SELECT COUNT(*) AS c FROM rooms WHERE house_id=?",
        (hid,)
    ).fetchone()["c"]
    return max_rooms, int(cnt)
