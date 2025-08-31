# landlord/house_form.py
from __future__ import annotations

from datetime import datetime as dt
from typing import Dict, Any, Iterable, List

# We can reuse these pure helpers from your utils module
from utils import validate_city_active, valid_choice


Truthies: Iterable[str] = ("1", "true", "on", "yes", "True", True, 1)


def _bool(form: Dict[str, Any], name: str, default: int = 0) -> int:
    """
    Return 1/0 from a checkbox-like field in a generic mapping (e.g., request.form).
    """
    v = form.get(name, None)
    if v is None:
        return default
    return 1 if v in Truthies else 0


def derive_bills_utilities(bills_option: str, form: Dict[str, Any]) -> Dict[str, int]:
    """
    Compute detailed utility flags based on the selected bills_option.
    - 'yes'  -> all utilities = 1
    - 'no'   -> all utilities = 0
    - 'some' -> read individual checkboxes from form
    """
    if bills_option == "yes":
        return dict(
            bills_util_gas=1,
            bills_util_electric=1,
            bills_util_water=1,
            bills_util_broadband=1,
            bills_util_tv=1,
        )
    if bills_option == "some":
        return dict(
            bills_util_gas=_bool(form, "bills_util_gas"),
            bills_util_electric=_bool(form, "bills_util_electric"),
            bills_util_water=_bool(form, "bills_util_water"),
            bills_util_broadband=_bool(form, "bills_util_broadband"),
            bills_util_tv=_bool(form, "bills_util_tv"),
        )
    # default: 'no'
    return dict(
        bills_util_gas=0,
        bills_util_electric=0,
        bills_util_water=0,
        bills_util_broadband=0,
        bills_util_tv=0,
    )


def parse_house_form(form: Dict[str, Any], *, default_listing_type: str) -> Dict[str, Any]:
    """
    Parse incoming form mapping into a normalized payload dict ready for insert/update.
    This does NOT touch the database. Call validate_house() afterwards.
    """
    title = (form.get("title") or "").strip()
    city = (form.get("city") or "").strip()
    address = (form.get("address") or "").strip()
    letting_type = (form.get("letting_type") or "").strip()
    gender_pref = (form.get("gender_preference") or "").strip()

    # Bills model (dropdown comes from <select name="bills_included">)
    bills_option = (form.get("bills_included") or "no").strip().lower()
    if bills_option not in ("yes", "no", "some"):
        bills_option = "no"
    # Keep legacy boolean in sync for older parts of the app
    bills_included_legacy = 1 if bills_option == "yes" else 0

    # Detailed utilities derived from option + checkboxes
    bills_detail = derive_bills_utilities(bills_option, form)

    shared_bathrooms = int(form.get("shared_bathrooms") or 0)
    bedrooms_total = int(form.get("bedrooms_total") or 0)
    listing_type = (form.get("listing_type") or default_listing_type or "owner").strip()

    # Amenities (form names kept exactly as existing templates)
    payload = dict(
        title=title,
        city=city,
        address=address,
        letting_type=letting_type,
        bedrooms_total=bedrooms_total,
        gender_preference=gender_pref,

        bills_option=bills_option,
        bills_included=bills_included_legacy,
        shared_bathrooms=shared_bathrooms,

        washing_machine=_bool(form, "washing_machine", default=1),
        tumble_dryer=_bool(form, "tumble_dryer"),
        dishwasher=_bool(form, "dishwasher"),
        cooker=_bool(form, "cooker", default=1),
        microwave=_bool(form, "microwave"),
        coffee_maker=_bool(form, "coffee_maker"),

        central_heating=_bool(form, "central_heating", default=1),
        air_con=_bool(form, "air_conditioning"),  # note: form field is air_conditioning
        vacuum=_bool(form, "vacuum"),

        wifi=_bool(form, "wifi", default=1),
        wired_internet=_bool(form, "wired_internet"),
        common_area_tv=_bool(form, "common_area_tv"),

        cctv=_bool(form, "cctv"),
        video_door_entry=_bool(form, "video_door_entry"),
        fob_entry=_bool(form, "fob_entry"),

        off_street_parking=_bool(form, "off_street_parking"),
        local_parking=_bool(form, "local_parking"),
        garden=_bool(form, "garden"),
        roof_terrace=_bool(form, "roof_terrace"),
        bike_storage=_bool(form, "bike_storage"),

        games_room=_bool(form, "games_room"),
        cinema_room=_bool(form, "cinema_room"),

        cleaning_service=(form.get("cleaning_service") or "none").strip(),
        listing_type=listing_type,

        created_at=dt.utcnow().isoformat(),  # used for inserts
    )

    # Merge detailed bills
    payload.update(bills_detail)
    return payload


def validate_house(payload: Dict[str, Any]) -> List[str]:
    """
    Return a list of human-readable error messages. Empty list means OK.
    """
    errors: List[str] = []

    title = payload.get("title", "").strip()
    city = payload.get("city", "").strip()
    address = payload.get("address", "").strip()
    letting_type = payload.get("letting_type", "").strip()
    gender_pref = payload.get("gender_preference", "").strip()
    cleaning_service = payload.get("cleaning_service", "").strip()
    listing_type = payload.get("listing_type", "").strip()
    bedrooms_total = int(payload.get("bedrooms_total") or 0)

    if not title:
        errors.append("Title is required.")
    if not address:
        errors.append("Address is required.")
    if bedrooms_total < 1:
        errors.append("Bedrooms must be at least 1.")
    if not validate_city_active(city):
        errors.append("Please choose a valid active city.")
    if not valid_choice(letting_type, ("whole", "share")):
        errors.append("Invalid letting type.")
    if not valid_choice(gender_pref, ("Male", "Female", "Mixed", "Either")):
        errors.append("Invalid gender preference.")
    if not valid_choice(cleaning_service, ("none", "weekly", "fortnightly", "monthly")):
        errors.append("Invalid cleaning service value.")
    if not valid_choice(listing_type, ("owner", "agent")):
        errors.append("Invalid listing type.")

    # bills_option sanity check (already normalized in parse)
    if payload.get("bills_option") not in ("yes", "no", "some"):
        errors.append("Invalid bills option.")

    return errors
