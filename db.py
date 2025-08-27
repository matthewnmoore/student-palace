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
      -- is_verified/role added by migrations below if missing
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
      -- listing_type added by migration below if missing
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

    # House images (processed, resized + watermarked)
    c.execute("""
    CREATE TABLE IF NOT EXISTS house_images(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      house_id INTEGER NOT NULL,
      file_name TEXT NOT NULL,          -- basename only, e.g. abc123.jpg
      file_path TEXT NOT NULL,          -- relative path under /static, e.g. uploads/houses/abc123.jpg
      width INTEGER NOT NULL,
      height INTEGER NOT NULL,
      bytes INTEGER NOT NULL,
      is_primary INTEGER NOT NULL DEFAULT 0,  -- 1 = primary image for the house
      created_at TEXT NOT NULL,
      FOREIGN KEY (house_id) REFERENCES houses(id) ON DELETE CASCADE
    );
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_house_images_house_id ON house_images(house_id);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_house_images_primary ON house_images(house_id,is_primary);")

    conn.commit()

    # --- Migrations (non-destructive) ---

    # landlords.created_at
    if not table_has_column(conn, "landlords", "created_at"):
        conn.execute("ALTER TABLE landlords ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        conn.commit()
        now = dt.utcnow().isoformat()
        conn.execute(
            "UPDATE landlords SET created_at=? WHERE created_at='' OR created_at IS NULL",
            (now,),
        )
        conn.commit()

    # landlord_profiles.is_verified
    if not table_has_column(conn, "landlord_profiles", "is_verified"):
        conn.execute("ALTER TABLE landlord_profiles ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0;")
        conn.commit()

    # landlord_profiles.role  ('owner' | 'agent') default 'owner'
    if not table_has_column(conn, "landlord_profiles", "role"):
        conn.execute("ALTER TABLE landlord_profiles ADD COLUMN role TEXT NOT NULL DEFAULT 'owner';")
        conn.commit()
        conn.execute("""
            UPDATE landlord_profiles
               SET role = CASE
                    WHEN LOWER(COALESCE(role,'')) IN ('owner','agent') THEN LOWER(role)
                    ELSE 'owner'
               END
        """)
        conn.commit()

    # houses.listing_type ('owner' | 'agent') default 'owner'
    if not table_has_column(conn, "houses", "listing_type"):
        conn.execute("ALTER TABLE houses ADD COLUMN listing_type TEXT NOT NULL DEFAULT 'owner';")
        conn.commit()
        conn.execute("""
            UPDATE houses
               SET listing_type = CASE
                    WHEN LOWER(COALESCE(listing_type,'')) IN ('owner','agent') THEN LOWER(listing_type)
                    ELSE 'owner'
               END
        """)
        conn.commit()

    conn.close()
