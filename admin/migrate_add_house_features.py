# admin/migrate_add_house_features.py
from __future__ import annotations

import sqlite3
from db import get_db  # same helper you use elsewhere

# Five short feature fields (max ~40 chars each)
MISSING_COLS = [
    ("feature1", "TEXT CHECK (length(feature1) <= 40)"),
    ("feature2", "TEXT CHECK (length(feature2) <= 40)"),
    ("feature3", "TEXT CHECK (length(feature3) <= 40)"),
    ("feature4", "TEXT CHECK (length(feature4) <= 40)"),
    ("feature5", "TEXT CHECK (length(feature5) <= 40)"),
]

def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)  # r[1] is column name

def run() -> str:
    """
    Idempotent migration: adds missing columns to 'houses'.
    Safe to run multiple times.
    """
    conn = get_db()
    added, skipped = [], []
    try:
        for name, decl in MISSING_COLS:
            if not _has_column(conn, "houses", name):
                conn.execute(f"ALTER TABLE houses ADD COLUMN {name} {decl}")
                added.append(name)
            else:
                skipped.append(name)
        conn.commit()
    finally:
        conn.close()

    parts = []
    if added:
        parts.append(f"Added: {', '.join(added)}")
    if skipped:
        parts.append(f"Already existed: {', '.join(skipped)}")
    if not parts:
        parts.append("Nothing to do.")
    return " | ".join(parts)

if __name__ == "__main__":
    print(run())
