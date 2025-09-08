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

def _fk_targets(conn: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    """Returns list of (table, column) FK targets for given table."""
    try:
        rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        out = []
        for r in rows:
            # row fields: id, seq, table, from, to, on_update, on_delete, match
            t = r["table"] if isinstance(r, sqlite3.Row) else r[2]
            to_col = r["to"] if isinstance(r, sqlite3.Row) else r[5]
            out.append((t, to_col))
        return out
    except Exception:
        return []

def _rebuild_landlord_accreditations(conn: sqlite3.Connection) -> None:
    """
    Ensure landlord_accreditations references accreditation_types(id).
    If it currently targets accreditation_schemes, rebuild it.
    """
    # If table doesn't exist, create the correct shape and return.
    exists = conn.execute("""
        SELECT name FROM sqlite_master
         WHERE type='table' AND name='landlord_accreditations'
    """).fetchone()

    wants_sql = """
        CREATE TABLE landlord_accreditations_new(
            landlord_id INTEGER NOT NULL,
            scheme_id   INTEGER NOT NULL,
            extra_text  TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (landlord_id, scheme_id),
            FOREIGN KEY (landlord_id) REFERENCES landlords(id) ON DELETE CASCADE,
            FOREIGN KEY (scheme_id)   REFERENCES accreditation_types(id) ON DELETE CASCADE
        )
    """

    if not exists:
        conn.execute(wants_sql)
        conn.execute("ALTER TABLE landlord_accreditations_new RENAME TO landlord_accreditations")
        conn.commit()
        return

    # If exists, check current FK targets.
    targets = _fk_targets(conn, "landlord_accreditations")
    # Look for any FK pointing at accreditation_schemes
    points_to_old = any(t[0] == "accreditation_schemes" for t in targets)

    if not points_to_old:
        # Already fine (or has no FKs); make sure columns exist then exit.
        if not _table_has_column(conn, "landlord_accreditations", "extra_text"):
            conn.execute("ALTER TABLE landlord_accreditations ADD COLUMN extra_text TEXT NOT NULL DEFAULT ''")
            conn.commit()
        return

    # Rebuild: copy data across (best effort) then swap tables.
    conn.execute("BEGIN")
    try:
        conn.execute(wants_sql)
        # Copy what we can (if old table had the same columns)
        try:
            conn.execute("""
                INSERT OR IGNORE INTO landlord_accreditations_new(landlord_id, scheme_id, extra_text)
                SELECT landlord_id, scheme_id, COALESCE(extra_text,'')
                  FROM landlord_accreditations
            """)
        except Exception:
            # Fallback: copy without extra_text if column didn't exist
            conn.execute("""
                INSERT OR IGNORE INTO landlord_accreditations_new(landlord_id, scheme_id, extra_text)
                SELECT landlord_id, scheme_id, ''
                  FROM landlord_accreditations
            """)
        conn.execute("DROP TABLE landlord_accreditations")
        conn.execute("ALTER TABLE landlord_accreditations_new RENAME TO landlord_accreditations")
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def ensure_extra_schema() -> None:
    """
    Add-only, idempotent schema tweaks:
      - site_settings defaults
      - students + student_favourites
      - accreditation_types master list
      - landlord_accreditations junction with FK -> accreditation_types
    """
    conn = get_db()
    try:
        # site_settings
        conn.execute("""
            CREATE TABLE IF NOT EXISTS site_settings(
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
        """)
        defaults = {
            "show_metric_landlords": "1",
            "show_metric_houses": "1",
            "show_metric_rooms": "1",
            "show_metric_students": "0",
            "show_metric_photos": "0",
            "terms_md": "",
            "signups_enabled": "1",
            "logins_enabled":  "1",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO site_settings (key, value) VALUES (?, ?)",
                (k, v),
            )

        # students
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
        if not _table_has_column(conn, "students", "phone_number"):
            conn.execute("ALTER TABLE students ADD COLUMN phone_number TEXT NOT NULL DEFAULT ''")
        if not _table_has_column(conn, "students", "updated_at"):
            conn.execute("ALTER TABLE students ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

        # favourites
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

        # accreditation_types (admin-managed list)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accreditation_types(
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT UNIQUE NOT NULL,
                slug       TEXT UNIQUE NOT NULL,
                is_active  INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                help_text  TEXT NOT NULL DEFAULT ''
            )
        """)

        # landlord_accreditations must reference accreditation_types
        _rebuild_landlord_accreditations(conn)

        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
