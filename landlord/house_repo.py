from __future__ import annotations

from typing import Dict, Any, Sequence

# Columns we set on both INSERT and UPDATE (excluding landlord_id / created_at / id filters)
_COMMON_COLS: Sequence[str] = (
    "title",
    "description",   # <-- persist description
    "city",
    "address",
    "letting_type",
    "bedrooms_total",
    "gender_preference",
    "bills_included",
    "bills_option",
    "bills_util_gas",
    "bills_util_electric",
    "bills_util_water",
    "bills_util_broadband",
    "bills_util_tv",
    "shared_bathrooms",
    "washing_machine",
    "tumble_dryer",
    "dishwasher",
    "cooker",
    "microwave",
    "coffee_maker",
    "central_heating",
    "air_con",
    "vacuum",
    "wifi",
    "wired_internet",
    "common_area_tv",
    "cctv",
    "video_door_entry",
    "fob_entry",
    "off_street_parking",
    "local_parking",
    "garden",
    "roof_terrace",
    "bike_storage",
    "games_room",
    "cinema_room",
    "cleaning_service",
    "listing_type",
    "epc_rating",     # optional A–G (or empty)
    "youtube_url",    # persist YouTube link
    # ✅ NEW: 5 short feature highlights
    "feature1",
    "feature2",
    "feature3",
    "feature4",
    "feature5",
)

def _values_from_payload(payload: Dict[str, Any], cols: Sequence[str]) -> list:
    """Extract values from payload in column order (no casting here)."""
    return [payload.get(c) for c in cols]

def insert_house(conn, landlord_id: int, payload: Dict[str, Any]) -> int:
    """
    Insert a house row for a given landlord.
    Expects payload to already be validated/normalized (see houses._parse_or_delegate or house_form.parse_house_form).
    Returns the new house id.
    """
    cols = ["landlord_id", *list(_COMMON_COLS), "created_at"]
    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT INTO houses({','.join(cols)}) VALUES ({placeholders})"

    vals = [landlord_id, *_values_from_payload(payload, _COMMON_COLS), payload.get("created_at")]
    cur = conn.execute(sql, vals)
    conn.commit()
    return int(cur.lastrowid)

def update_house(conn, landlord_id: int, house_id: int, payload: Dict[str, Any]) -> None:
    """
    Update a landlord-owned house by id.
    Expects payload to already be validated/normalized.
    """
    assignments = ", ".join([f"{c}=?" for c in _COMMON_COLS])
    sql = f"""
        UPDATE houses
           SET {assignments}
         WHERE id=? AND landlord_id=?
    """
    vals = [*_values_from_payload(payload, _COMMON_COLS), house_id, landlord_id]
    conn.execute(sql, vals)
    conn.commit()
