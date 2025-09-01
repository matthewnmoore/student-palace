from utils import clean_bool
from db import get_db

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
    errors = []
    if not name:
        errors.append("Room name is required.")
    if bed_size not in ("Single","Small double","Double","King"):
        errors.append("Please choose a valid bed size.")
    return ({
        "name": name, "ensuite": ensuite, "bed_size": bed_size, "tv": tv,
        "desk_chair": desk_chair, "wardrobe": wardrobe, "chest_drawers": chest_drawers,
        "lockable_door": lockable_door, "wired_internet": wired_internet, "room_size": room_size
    }, errors)

def room_counts(conn, hid):
    row = conn.execute("SELECT bedrooms_total FROM houses WHERE id=?", (hid,)).fetchone()
    max_rooms = int(row["bedrooms_total"]) if row else 0
    cnt = conn.execute("SELECT COUNT(*) AS c FROM rooms WHERE house_id=?", (hid,)).fetchone()["c"]
    return max_rooms, int(cnt)
