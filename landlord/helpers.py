from utils import clean_bool
from datetime import datetime as dt

# IMPORTANT: This helper now only PARSES input.
# It does NOT heal dates. The route will heal dates AFTER it knows is_let for sure.


def _parse_uk_date(value: str) -> str:
    """
    Accept 'DD/MM/YYYY' (UK) or 'YYYY-MM-DD' (HTML) and return ISO 'YYYY-MM-DD'.
    Return '' if empty/invalid.
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

    description = (request.form.get("description") or "").strip()

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

    couples_ok = clean_bool("couples_ok")
    disabled_ok = clean_bool("disabled_ok")

    # NOTE: is_let will be reparsed robustly in the route.
    is_let = clean_bool("is_let")

    # Dates: parse only; no healing here
    available_from_iso = _parse_uk_date((request.form.get("available_from") or "").strip())
    let_until_iso = _parse_uk_date((request.form.get("let_until") or "").strip())

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
        # raw values; route will heal based on correct is_let
        "is_let": is_let,
        "available_from": available_from_iso,
        "let_until": let_until_iso,
    }, errors)


def room_counts(conn, hid):
    row = conn.execute("SELECT bedrooms_total FROM houses WHERE id=?", (hid,)).fetchone()
    max_rooms = int(row["bedrooms_total"]) if row else 0
    cnt = conn.execute("SELECT COUNT(*) AS c FROM rooms WHERE house_id=?", (hid,)).fetchone()["c"]
    return max_rooms, int(cnt)
