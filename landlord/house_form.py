# landlord/house_form.py
from __future__ import annotations

from typing import Optional, Mapping


def get_default_listing_type(conn, landlord_id: int, existing: Optional[Mapping] = None) -> str:
    """
    Decide the default listing type for the house form.

    Priority:
      1) If an existing house dict/row is supplied and it already has a
         listing_type of 'owner' or 'agent', use that.
      2) Otherwise, look up the landlord's profile role and return it if valid.
      3) Fallback to 'owner'.

    This mirrors the prior inline logic used in houses.py so behaviour remains identical.
    """
    # Case 1: existing house (edit mode) already has a listing_type
    if existing:
        # existing may be a dict or sqlite3.Row; both support key access by string
        try:
            lt = existing.get("listing_type")  # dict-like
        except AttributeError:
            # sqlite3.Row fallback
            lt = existing["listing_type"] if "listing_type" in existing.keys() else None

        if isinstance(lt, str) and lt.lower() in ("owner", "agent"):
            return lt.lower()

    # Case 2: pull landlord's profile role from DB
    try:
        row = conn.execute(
            "SELECT role FROM landlord_profiles WHERE landlord_id=?",
            (landlord_id,),
        ).fetchone()
    except Exception:
        row = None

    role = None
    if row:
        try:
            role = row["role"]
        except Exception:
            role = None

    if isinstance(role, str) and role.lower() in ("owner", "agent"):
        return role.lower()

    # Case 3: safe fallback
    return "owner"
