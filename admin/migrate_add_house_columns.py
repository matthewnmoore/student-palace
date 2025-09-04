# admin/migrate_add_house_columns.py
from __future__ import annotations

import sqlite3
from models import get_db

MISSING_COLS = [
    ("ensuites_available", "INTEGER NOT NULL DEFAULT 0"),
    ("double_beds_available", "INTEGER NOT NULL DEFAULT 0"),
    ("couples_ok_available", "INTEGER NOT NULL DEFAULT 0"),
]

def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    row = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in row)  # r[1] is the column name

def run() -> str:
    """
    Idempotent migration: adds missing columns to houses.
    Returns a short status string for display.
    """
    conn = get_db()
    added = []
    skipped = []
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
