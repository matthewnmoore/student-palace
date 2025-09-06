# admin/schema.py
from __future__ import annotations
import sqlite3
from db import get_db

def ensure_extra_schema() -> None:
    """Make sure students, favourites, and site_settings tables exist safely."""
    conn = get_db()
    try:
        # Students
        conn.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                display_name TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT ''
            )
        """)

        # Student favourites
        conn.execute("""
            CREATE TABLE IF NOT EXISTS student_favourites (
                student_id INTEGER NOT NULL,
                house_id INTEGER,
                room_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (student_id, house_id, room_id),
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY (house_id) REFERENCES houses(id) ON DELETE CASCADE,
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            )
        """)

        # Site settings (admin controls display of counts)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS site_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                show_landlords INTEGER NOT NULL DEFAULT 1,
                show_houses INTEGER NOT NULL DEFAULT 1,
                show_rooms INTEGER NOT NULL DEFAULT 1,
                show_photos INTEGER NOT NULL DEFAULT 1,
                show_students INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("INSERT OR IGNORE INTO site_settings (id) VALUES (1)")

        # Add created_at to house_images if missing
        cols = [r[1] for r in conn.execute("PRAGMA table_info(house_images)").fetchall()]
        if "created_at" not in cols:
            conn.execute("ALTER TABLE house_images ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")

        conn.commit()
    finally:
        conn.close()
