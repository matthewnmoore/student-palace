import sqlite3
from datetime import datetime as dt
from config import DB_PATH

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return conn

def table_has_column(conn, table, column):
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        cols = [r["name"] for r in cur.fetchall()]
        return column in cols
    except Exception:
        return False

def ensure_db():
    conn = get_db()
    c = conn.cursor()

    # Cities
    c.execute("""
    CREATE TABLE IF NOT EXISTS cities(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1
    );
    """)

    # Landlords
    c.execute("""
    CREATE TABLE IF NOT EXISTS landlords(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    """)

    # Landlord profiles (1–1)
    c.execute("""
    CREATE TABLE IF NOT EXISTS landlord_profiles(
      landlord_id INTEGER PRIMARY KEY,
      display_name TEXT,
      phone TEXT,
      website TEXT,
      bio TEXT,
      public_slug TEXT UNIQUE,
      profile_views INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY (landlord_id) REFERENCES landlords(id) ON DELETE CASCADE
    );
    """)

    # Houses
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

    # Rooms
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

    # Migrations (non-destructive)
    if not table_has_column(conn, "landlords", "created_at"):
        conn.execute("ALTER TABLE landlords ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        conn.commit()
        now = dt.utcnow().isoformat()
        conn.execute("UPDATE landlords SET created_at=? WHERE created_at='' OR created_at IS NULL", (now,))
        conn.commit()

    conn.close()
