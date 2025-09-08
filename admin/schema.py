# admin/schema.py
from __future__ import annotations
import sqlite3
from db import get_db

def migrate_accreditations_schema(conn: sqlite3.Connection) -> None:
    """
    Ensure landlord_accreditations references accreditation_types and uses:
      landlord_id | accreditation_id | note
    If an older table (scheme_id/extra_text → accreditation_schemes) exists,
    rebuild it and migrate any rows by matching on the accreditation NAME.
    Safe to run repeatedly.
    """
    def cols(table: str) -> set[str]:
        try:
            return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            return set()

    # Already correct? nothing to do.
    lac = cols("landlord_accreditations")
    if {"landlord_id", "accreditation_id", "note"} <= lac:
        return

    # Old shape present?
    if {"landlord_id", "scheme_id", "extra_text"} <= lac:
        # How many rows to migrate?
        try:
            cnt = conn.execute("SELECT COUNT(*) AS c FROM landlord_accreditations").fetchone()["c"]
        except Exception:
            cnt = 0

        # Rebuild table (SQLite requires table swap for FK changes)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS landlord_accreditations_new(
                landlord_id INTEGER NOT NULL,
                accreditation_id INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (landlord_id, accreditation_id),
                FOREIGN KEY (landlord_id) REFERENCES landlords(id) ON DELETE CASCADE,
                FOREIGN KEY (accreditation_id) REFERENCES accreditation_types(id) ON DELETE CASCADE
            )
        """)

        if cnt > 0:
            # Migrate by NAME: accreditation_schemes.name == accreditation_types.name
            conn.execute("""
                INSERT OR IGNORE INTO landlord_accreditations_new (landlord_id, accreditation_id, note)
                SELECT la.landlord_id,
                       at.id    AS accreditation_id,
                       la.extra_text AS note
                  FROM landlord_accreditations la
                  JOIN accreditation_schemes s ON s.id = la.scheme_id
                  JOIN accreditation_types  at ON at.name = s.name
            """)

        conn.execute("DROP TABLE landlord_accreditations")
        conn.execute("ALTER TABLE landlord_accreditations_new RENAME TO landlord_accreditations")

        conn.execute("COMMIT")
        conn.execute("PRAGMA foreign_keys=ON")
        return

    # Table missing entirely → create the correct one
    conn.execute("""
        CREATE TABLE IF NOT EXISTS landlord_accreditations(
            landlord_id INTEGER NOT NULL,
            accreditation_id INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (landlord_id, accreditation_id),
            FOREIGN KEY (landlord_id) REFERENCES landlords(id) ON DELETE CASCADE,
            FOREIGN KEY (accreditation_id) REFERENCES accreditation_types(id) ON DELETE CASCADE
        )
    """)

def ensure_extra_schema() -> None:
    """Called from admin/__init__.py at import time."""
    conn = get_db()
    try:
        migrate_accreditations_schema(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass
