# admin/schema.py
from __future__ import annotations

import sqlite3
from db import get_db

def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = [r["name"] if isinstance(r, sqlite3.Row) else r[1] for r in cols]
        return column in names
    except Exception:
        return False

def ensure_extra_schema() -> None:
    """
    Add-only, idempotent schema tweaks:
      - site_settings (key,value) + default flags and text entries
      - students table (with phone_number, updated_at)
      - student_favourites mapping (no-op if it already exists)
    """
    conn = get_db()
    try:
        # 1) site_settings (key/value)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS site_settings(
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
        """)

        # Defaults (use key, not id)
        defaults = {
            # footer metrics toggles
            "show_metric_landlords": "1",
            "show_metric_houses": "1",
            "show_metric_rooms": "1",
            "show_metric_students": "0",
            "show_metric_photos": "0",

            # editable Terms text (Markdown/HTML)
            "terms_md": "",

            # global auth toggles
            "signups_enabled": "1",
            "logins_enabled":  "1",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO site_settings (key, value) VALUES (?, ?)",
                (k, v),
            )

        # 2) students table (simple)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS students(
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT UNIQUE NOT NULL,
                name          TEXT NOT NULL DEFAULT '',
                phone_number  TEXT NOT NULL DEFAULT '',
                created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
                updated_at    TEXT NOT NULL DEFAULT ''
            )
        """)
        # If students already existed without columns, add them
        if not _table_has_column(conn, "students", "phone_number"):
            conn.execute("ALTER TABLE students ADD COLUMN phone_number TEXT NOT NULL DEFAULT ''")
        if not _table_has_column(conn, "students", "updated_at"):
            conn.execute("ALTER TABLE students ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

        # 3) favourites (optional; safe if already present)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS student_favourites(
                student_id INTEGER NOT NULL,
                house_id   INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
                PRIMARY KEY (student_id, house_id),
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY (house_id)   REFERENCES houses(id)   ON DELETE CASCADE
            )
        """)

        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
