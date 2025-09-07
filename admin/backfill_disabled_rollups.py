# admin/backfill_disabled_rollups.py
from __future__ import annotations

from db import get_db
from utils_summaries import recompute_all_houses_disabled


def run() -> str:
    """
    Idempotent backfill: (re)computes disabled-related rollups for every house.
    Safe to run multiple times.
    """
    conn = get_db()
    try:
        updated = recompute_all_houses_disabled(conn)
        return f"Backfill complete: {updated} houses updated."
    finally:
        conn.close()


if __name__ == "__main__":
    print(run())
