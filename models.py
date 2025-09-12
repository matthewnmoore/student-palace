# models.py
from __future__ import annotations

import sqlite3
from typing import List
from db import get_db

# ------------------------------------------------------------
# Internal helpers (safe, idempotent)
# ------------------------------------------------------------
def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if a table has the given column name."""
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return any(r["name"] == column for r in cur.fetchall())
    except Exception:
        return False


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def _safe_alter_add_column(conn: sqlite3.Connection, table: str, col_decl: str) -> None:
    """
    Add a column with "ALTER TABLE ... ADD COLUMN ..." if it doesn't exist.
    col_decl must start with the column name (e.g. "postcode_prefixes TEXT NOT NULL DEFAULT ''").
    """
    try:
        col_name = col_decl.strip().split()[0]
        if not _table_has_column(conn, table, col_name):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_decl}")
            conn.commit()
    except Exception as e:
        print(f"[models] Skipped add column on {table}: {col_decl} ({e})")


def _ensure_admin_schema() -> None:
    """
    Non-destructive bootstrap for fields we now depend on from admin UI:
      - cities.postcode_prefixes (TEXT, CSV list of prefixes)
      - cities.sort_order (INTEGER, for admin drag-sort)
      - accreditation_types (admin-managed list)
      - landlord_accreditations (junction with optional note)
    Runs at import time; safe to call repeatedly.
    """
    conn = None
    try:
        conn = get_db()

        # Ensure cities table exists (created elsewhere in app); if not, create a minimal version
        if not _table_exists(conn, "cities"):
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cities(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT UNIQUE NOT NULL,
                  is_active INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.commit()

        # Add admin-managed columns on cities
        _safe_alter_add_column(conn, "cities", "postcode_prefixes TEXT NOT NULL DEFAULT ''")
        _safe_alter_add_column(conn, "cities", "sort_order INTEGER NOT NULL DEFAULT 0")

        # Accreditations master table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accreditation_types(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                help_text TEXT NOT NULL DEFAULT ''
            )
        """)
        # Junction: landlords ↔ accreditations (with optional note, e.g. membership number)
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
        conn.commit()

        # Defensive: backfill slug if any rows missing it (older DBs created without slug)
        try:
            rows = conn.execute("SELECT id, name, slug FROM accreditation_types").fetchall()
            for r in rows:
                rid = r["id"] if isinstance(r, sqlite3.Row) else r[0]
                name = (r["name"] if isinstance(r, sqlite3.Row) else r[1]) or ""
                slug = (r["slug"] if isinstance(r, sqlite3.Row) else r[2]) or ""

                if not str(slug).strip():
                    base = "".join(ch.lower() if str(ch).isalnum() else "-" for ch in name)
                    base = "-".join([p for p in base.split("-") if p])
                    if not base:
                        base = f"acc-{rid}"
                    candidate = base
                    i = 2
                    while conn.execute(
                        "SELECT 1 FROM accreditation_types WHERE slug=? AND id<>?",
                        (candidate, rid)
                    ).fetchone():
                        candidate = f"{base}-{i}"
                        i += 1
                    conn.execute("UPDATE accreditation_types SET slug=? WHERE id=?", (candidate, rid))
            conn.commit()
        except Exception as e:
            print("[models] Accreditation slug backfill skipped:", e)

    except Exception as e:
        print("[models] _ensure_admin_schema:", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# Run the admin-related schema bootstrap at import time.
_ensure_admin_schema()


# ------------------------------------------------------------
# Public helpers (used by views/templates)
# ------------------------------------------------------------
def get_active_cities_safe(order_by_admin: bool = True):
    """
    Returns a list of active city rows (sqlite3.Row).
    If cities.sort_order exists and order_by_admin=True, order by sort_order then name.
    Otherwise, order by name.
    On any DB error, returns [] (safe for templates).
    """
    conn = None
    try:
        conn = get_db()
        order_clause = "ORDER BY name ASC"
        if order_by_admin and _table_has_column(conn, "cities", "sort_order"):
            order_clause = "ORDER BY sort_order ASC, name ASC"
        rows = conn.execute(
            f"SELECT * FROM cities WHERE is_active=1 {order_clause}"
        ).fetchall()
        return rows
    except Exception as e:
        print("[WARN] get_active_cities_safe:", e)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_active_city_names(order_by_admin: bool = True) -> List[str]:
    """Convenience helper: returns just the active city names."""
    return [r["name"] for r in get_active_cities_safe(order_by_admin=order_by_admin)]


def validate_city_active(city: str) -> bool:
    """True if the given city exists and is marked active."""
    if not city:
        return False
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT 1 FROM cities WHERE name=? AND is_active=1",
            (city,)
        ).fetchone()
        return bool(row)
    except Exception:
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ============================================================
# SQLAlchemy ORM models (Step 1)
# ============================================================
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class City(Base):
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    is_active = Column(Integer, nullable=False, default=1)


class Landlord(Base):
    __tablename__ = "landlords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    profile = relationship("LandlordProfile", back_populates="landlord", uselist=False)


class LandlordProfile(Base):
    __tablename__ = "landlord_profiles"

    landlord_id = Column(Integer, ForeignKey("landlords.id"), primary_key=True)
    display_name = Column(String)
    phone = Column(String)
    website = Column(String)
    bio = Column(Text)
    public_slug = Column(String, unique=True)
    profile_views = Column(Integer, default=0)
    is_verified = Column(Integer, default=0)
    role = Column(String, default="owner")  # owner / agent
    logo_path = Column(String)
    photo_path = Column(String)
    enable_new_landlord = Column(Integer, default=1)

    landlord = relationship("Landlord", back_populates="profile")
