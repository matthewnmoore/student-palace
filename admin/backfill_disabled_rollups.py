# admin/backfill_disabled_rollups.py
from __future__ import annotations
from db import get_db
from utils_summaries import recompute_all_houses_disabled

def run() -> str:
    """
    Recompute disabled-related house rollups for ALL houses.
    Safe and idempotent.
    """
    conn = get_db()
    try:
        n = recompute_all_houses_disabled(conn)
        return f"Processed {n} houses."
    finally:
        try:
            conn.close()
        except Exception:
            pass
