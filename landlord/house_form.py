# landlord/house_form.py
from __future__ import annotations

from typing import Optional, Mapping

def get_default_listing_type(conn, landlord_id: int, existing: Optional[Mapping] = None) -> str:
    """
    Decide the default listing type for the house form.

    Priority:
      1) If editing an existing house with a valid listing_type ('owner'/'agent'), use it.
      2) Otherwise, read landlord_profiles.role ('owner'/'agent') for this landlord.
      3) Fallback to 'owner'.
    """
    # 1) Existing house value (edit mode)
    if existing:
        try:
            lt = existing.get("listing_type")
        except AttributeError:
            lt = existing["listing_type"] if "listing_type" in existing.keys() else None
        if isinstance(lt, str) and lt.lower() in ("owner", "agent"):
            return lt.lower()

    # 2) Landlord profile role
    role = None
    try:
        row = conn.execute(
            "SELECT role FROM landlord_profiles WHERE landlord_id=?",
            (landlord_id,),
        ).fetchone()
        if row:
            try:
                role = row["role"]
            except Exception:
                role = None
    except Exception:
        role = None

    if isinstance(role, str) and role.lower() in ("owner", "agent"):
        return role.lower()

    # 3) Fallback
    return "owner"
