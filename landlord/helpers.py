from utils import clean_bool
from db import get_db  # kept for parity with your file, even if unused here
from datetime import datetime as dt, date, timedelta


def _parse_uk_date(value: str) -> str:
    """
    Accepts 'DD/MM/YYYY' (UK) or 'YYYY-MM-DD' (HTML date input) and returns ISO 'YYYY-MM-DD'.
    Returns '' if empty or invalid.
    """
    if not value:
        return ""
    value = value.strip()
    if not value:
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = dt.strptime(value, fmt).date()
            return d.isoformat()
        except Exception:
            continue
    return ""


def _to_date(iso_str: str) -> date | None:
    """Convert 'YYYY-MM-DD' to date or None."""
    if not iso_str:
        return None
    try:
        return dt.strptime(iso_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def _june_30_next_year(today: date) -> date:
    """Always 30 June next calendar year from 'today'."""
    return date(today.year + 1, 6, 30)


def room_form_values(request):
    name = (request.form.get("name") or "").strip()
    ensuite = clean_bool("ensuite")
    bed_size = (request.form.get("bed_size") or "").strip()
    tv = clean_bool("tv")
    desk_chair = clean_bool("desk_chair")
    wardrobe = clean_bool("wardrobe")
    chest_drawers = clean_bool("chest_drawers")
    lockable_door = clean_bool("lockable_door")
    wired_internet = clean_bool("wired_internet")
    room_size = (request.form.get("room_size") or "").strip()

    # Description
    description = (request.form.get("description") or "").strip()

    # Price & extras
    raw_price = (request.form.get("price_pcm") or "").strip()
    try:
        price_pcm = int(raw_price.replace(",", ""))
    except Exception:
        price_pcm = 0
    safe = clean_bool("safe")
    dressing_table = clean_bool("dressing_table")
    mirror = clean_bool("mirror")
    bedside_table = clean_bool("bedside_table")
    blinds = clean_bool("blinds")
    curtains = clean_bool("curtains")
    sofa = clean_bool("sofa")

    # Searchable flags
    couples_ok = clean_bool("couples_ok")
    disabled_ok = clean_bool("disabled_ok")

    # Availability inputs (raw)
    is_let = clean_bool("is_let")  # may be wrong when hidden + checkbox both present — rooms.py will overwrite it
    available_from_in = (request.form.get("available_from") or "").strip()
    let_until_in = (request.form.get("let_until") or "").strip()

    available_from_iso = _parse_uk_date(available_from_in)
    let_until_iso = _parse_uk_date(let_until_in)

    # Self-healing date logic (first pass; safe even if rooms.py overwrites is_let)
    today = date.today()
    af = _to_date(available_from_iso)
    lu = _to_date(let_until_iso)

    if is_let:
        if not lu:
            lu = _june_30_next_year(today)
        if not af or af <= lu:
            af = lu + timedelta(days=1)
    else:
        if not af or af > today:
            af = today
        # Make "let_until" the day before "available_from" so searches have a clear boundary
        lu = af - timedelta(days=1)

    # Back to ISO for DB
    available_from_iso = _iso(af)
    let_until_iso = _iso(lu)

    # Validation (keep minimal; we already healed dates)
    errors = []
    if not name:
        errors.append("Room name is required.")
    if len(name) > 20:
        errors.append("Room name cannot be longer than 20 characters.")
    if len(description) > 1200:
        errors.append("Room description cannot be longer than 1200 characters.")
    if bed_size not in ("Single", "Small double", "Double", "King"):
        errors.append("Please choose a valid bed size.")

    return ({
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
        # Dates (already healed)
        "is_let": is_let,
        "available_from": available_from_iso,
        "let_until": let_until_iso,
    }, errors)


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
