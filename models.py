import os
import sqlite3
from datetime import datetime as dt

DB_PATH = os.environ.get("DB_PATH", "/opt/uploads/student_palace.db")

# Ensure the DB directory exists (works with Render disks too)
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return conn

def _table_has_column(conn, table, column):
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return column in [r["name"] for r in cur.fetchall()]
    except Exception:
        return False

def ensure_db():
    """
    Creates all tables if missing and applies safe, idempotent migrations.
    Run this once on startup (imports in app/__init__.py or main app entry).
    """
    conn = get_db()
    c = conn.cursor()

    # ---------- Core tables ----------
    c.execute("""
    CREATE TABLE IF NOT EXISTS cities(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1
      -- sort_order INTEGER, image_url TEXT added by migrations below
    );
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS landlords(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS landlord_profiles(
      landlord_id INTEGER PRIMARY KEY,
      display_name TEXT,
      phone TEXT,
      website TEXT,
      bio TEXT,
      public_slug TEXT UNIQUE,
      profile_views INTEGER NOT NULL DEFAULT 0
    );
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS houses(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      landlord_id INTEGER NOT NULL,
      title TEXT NOT NULL,
      city TEXT NOT NULL,
      address TEXT NOT NULL,
      letting_type TEXT NOT NULL CHECK (letting_type IN ('whole','share')),
      bedrooms_total INTEGER NOT NULL,
      gender_preference TEXT NOT NULL CHECK (gender_preference IN ('Male','Female','Mixed','Either')),
      bills_included INTEGER NOT NULL DEFAULT 0,
      shared_bathrooms INTEGER NOT NULL DEFAULT 0,

      off_street_parking INTEGER NOT NULL DEFAULT 0,
      local_parking INTEGER NOT NULL DEFAULT 0,
      cctv INTEGER NOT NULL DEFAULT 0,
      video_door_entry INTEGER NOT NULL DEFAULT 0,
      bike_storage INTEGER NOT NULL DEFAULT 0,
      cleaning_service TEXT NOT NULL DEFAULT 'none',
      wifi INTEGER NOT NULL DEFAULT 1,
      wired_internet INTEGER NOT NULL DEFAULT 0,
      common_area_tv INTEGER NOT NULL DEFAULT 0,

      created_at TEXT NOT NULL,

      FOREIGN KEY (landlord_id) REFERENCES landlords(id) ON DELETE CASCADE
    );
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS rooms(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      house_id INTEGER NOT NULL,
      name TEXT NOT NULL,
      ensuite INTEGER NOT NULL DEFAULT 0,

      bed_size TEXT NOT NULL CHECK (bed_size IN ('Single','Small double','Double','King')),
      tv INTEGER NOT NULL DEFAULT 0,
      desk_chair INTEGER NOT NULL DEFAULT 0,
      wardrobe INTEGER NOT NULL DEFAULT 0,
      chest_drawers INTEGER NOT NULL DEFAULT 0,
      lockable_door INTEGER NOT NULL DEFAULT 0,
      wired_internet INTEGER NOT NULL DEFAULT 0,

      room_size TEXT,
      created_at TEXT NOT NULL,

      FOREIGN KEY (house_id) REFERENCES houses(id) ON DELETE CASCADE
    );
    """)

    conn.commit()

    # ---------- Safe migrations ----------
    # cities.sort_order
    if not _table_has_column(conn, "cities", "sort_order"):
        c.execute("ALTER TABLE cities ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 1000;")
        conn.commit()
        # Give existing cities a deterministic order by name (A..Z)
        rows = c.execute("SELECT id FROM cities ORDER BY name ASC").fetchall()
        order = 1
        for r in rows:
            c.execute("UPDATE cities SET sort_order=? WHERE id=?", (order, r["id"]))
            order += 1
        conn.commit()

    # cities.image_url
    if not _table_has_column(conn, "cities", "image_url"):
        c.execute("ALTER TABLE cities ADD COLUMN image_url TEXT;")
        conn.commit()

    # landlords.created_at (older DBs)
    if not _table_has_column(conn, "landlords", "created_at"):
        c.execute("ALTER TABLE landlords ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        conn.commit()
        now = dt.utcnow().isoformat()
        c.execute("UPDATE landlords SET created_at=? WHERE created_at='' OR created_at IS NULL", (now,))
        conn.commit()

    conn.close()

# Run on import if you import models early (typical pattern)
ensure_db()
