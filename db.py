from __future__ import annotations

import os
import sqlite3
from datetime import datetime as dt
from pathlib import Path

# -----------------------------------------------------------------------------
# DB PATH (MUST be on persistent disk).
# -----------------------------------------------------------------------------
DEFAULT_DB_PATH = "/opt/render/project/src/static/uploads/houses/student_palace.db"
DB_PATH = os.environ.get("DB_PATH", DEFAULT_DB_PATH)

# Ensure the folder exists (safe on first run)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

print(f"[db] Using DB_PATH: {DB_PATH}")
try:
    p = Path(DB_PATH)
    if p.exists():
        print(f"[db] DB exists: size={p.stat().st_size} bytes")
    else:
        print("[db] DB does not exist yet; will be created on first connection.")
except Exception as e:
    print(f"[db] Could not stat DB_PATH: {e}")

# -----------------------------------------------------------------------------
# Connection helper (durability + safety)
# -----------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA mmap_size = 268435456")
    except Exception:
        pass
    return conn

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return bool(row)

def table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return any(r["name"] == column for r in cur.fetchall())
    except Exception:
        return False

def _safe_add_column(conn: sqlite3.Connection, table: str, ddl: str) -> None:
    """
    Add a column if it doesn't already exist. Example:
    _safe_add_column(conn, "houses", "ADD COLUMN epc_rating TEXT NOT NULL DEFAULT ''")
    """
    try:
        after = ddl.strip().split("ADD COLUMN", 1)[1].strip()
        col_name = after.split()[0]
        if not table_has_column(conn, table, col_name):
            conn.execute(f"ALTER TABLE {table} {ddl}")
            conn.commit()
    except Exception as e:
        print(f"[MIGRATE] Skipped '{ddl}' on {table}: {e}")

def _ensure_setting(conn: sqlite3.Connection, key: str, default_value: str) -> None:
    """
    Ensure a key exists in site_settings; insert with default_value if missing.
    """
    try:
        cur = conn.execute("SELECT 1 FROM site_settings WHERE key=?", (key,))
        if cur.fetchone() is None:
            conn.execute("INSERT INTO site_settings(key,value) VALUES(?,?)", (key, default_value))
            conn.commit()
    except Exception as e:
        print(f"[MIGRATE] ensure setting {key}:", e)

# -----------------------------------------------------------------------------
# Schema bootstrap + non-destructive migrations (never drop/delete)
# -----------------------------------------------------------------------------
def ensure_db():
    conn = get_db()
    c = conn.cursor()

    # --- Core tables ---
    c.execute("""
    CREATE TABLE IF NOT EXISTS cities(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1
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
      profile_views INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY (landlord_id) REFERENCES landlords(id) ON DELETE CASCADE
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

    # --- City → Postcode prefixes (for validation) ---
    c.execute("""
    CREATE TABLE IF NOT EXISTS city_postcodes(
      id     INTEGER PRIMARY KEY AUTOINCREMENT,
      city   TEXT NOT NULL,
      prefix TEXT NOT NULL,
      UNIQUE(city, prefix)
    );
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_city_postcodes_city ON city_postcodes(city)")

    # --- Global site settings (on/off toggles) ---
    c.execute("""
    CREATE TABLE IF NOT EXISTS site_settings(
      key   TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    """)
    conn.commit()
    _ensure_setting(conn, "logins_enabled",  "1")
    _ensure_setting(conn, "signups_enabled", "1")

    # --- Accreditation catalogue (admin) ---
    c.execute("""
    CREATE TABLE IF NOT EXISTS accreditation_schemes(
      id        INTEGER PRIMARY KEY AUTOINCREMENT,
      name      TEXT NOT NULL UNIQUE,
      is_active INTEGER NOT NULL DEFAULT 1
    );
    """)

    # --- Landlord selections (tick + optional text) ---
    c.execute("""
    CREATE TABLE IF NOT EXISTS landlord_accreditations(
      landlord_id INTEGER NOT NULL,
      scheme_id   INTEGER NOT NULL,
      extra_text  TEXT NOT NULL DEFAULT '',
      PRIMARY KEY (landlord_id, scheme_id),
      FOREIGN KEY (landlord_id) REFERENCES landlords(id) ON DELETE CASCADE,
      FOREIGN KEY (scheme_id)   REFERENCES accreditation_schemes(id) ON DELETE CASCADE
    );
    """)

    # --- House images ---
    if not table_exists(conn, "house_images"):
        c.execute("""
        CREATE TABLE house_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            bytes INTEGER NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            filename TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (house_id) REFERENCES houses(id) ON DELETE CASCADE
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_house_images_house ON house_images(house_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_house_images_primary ON house_images(house_id, is_primary DESC, sort_order ASC, id ASC);")


    # --- Room images (mirror of house_images) ---
    if not table_exists(conn, "room_images"):
        c.execute("""
        CREATE TABLE room_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,        -- relative under /static (e.g. uploads/rooms/xyz.jpg)
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            bytes INTEGER NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            filename TEXT NOT NULL,         -- canonical duplicate of file_name
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_room_images_room ON room_images(room_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_room_images_primary ON room_images(room_id, is_primary DESC, sort_order ASC, id ASC);")







    
    # --- House documents (EPC PDFs) ---
    if not table_exists(conn, "house_documents"):
        c.execute("""
        CREATE TABLE house_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            house_id INTEGER NOT NULL,
            doc_type TEXT NOT NULL,         -- 'epc' (future: other docs)
            file_name TEXT NOT NULL,        -- basename
            file_path TEXT NOT NULL,        -- relative under /static (e.g. uploads/houses/epc/xyz.pdf)
            bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            is_current INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (house_id) REFERENCES houses(id) ON DELETE CASCADE
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_house_docs_house ON house_documents(house_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_house_docs_current ON house_documents(house_id, doc_type, is_current)")

    conn.commit()

    # --- Non-destructive migrations ---
    if not table_has_column(conn, "landlords", "created_at"):
        conn.execute("ALTER TABLE landlords ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        conn.commit()
        now = dt.utcnow().isoformat()
        conn.execute(
            "UPDATE landlords SET created_at=? WHERE created_at='' OR created_at IS NULL",
            (now,),
        )
        conn.commit()

    _safe_add_column(conn, "landlord_profiles", "ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0")

    if not table_has_column(conn, "landlord_profiles", "role"):
        conn.execute("ALTER TABLE landlord_profiles ADD COLUMN role TEXT NOT NULL DEFAULT 'owner'")
        conn.commit()
        conn.execute("""
            UPDATE landlord_profiles
               SET role = CASE
                    WHEN LOWER(COALESCE(role,'')) IN ('owner','agent') THEN LOWER(role)
                    ELSE 'owner'
               END
        """)
        conn.commit()

    if not table_has_column(conn, "houses", "listing_type"):
        conn.execute("ALTER TABLE houses ADD COLUMN listing_type TEXT NOT NULL DEFAULT 'owner'")
        conn.commit()
        conn.execute("""
            UPDATE houses
               SET listing_type = CASE
                    WHEN LOWER(COALESCE(listing_type,'')) IN ('owner','agent') THEN LOWER(listing_type)
                    ELSE 'owner'
               END
        """)
        conn.commit()

    # --- Bills model (dropdown + detailed utilities) ---
    _safe_add_column(conn, "houses", "ADD COLUMN bills_option TEXT NOT NULL DEFAULT 'no'")
    _safe_add_column(conn, "houses", "ADD COLUMN bills_util_gas INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN bills_util_electric INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN bills_util_water INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN bills_util_broadband INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN bills_util_tv INTEGER NOT NULL DEFAULT 0")

    # --- Amenities (house) ---
    _safe_add_column(conn, "houses", "ADD COLUMN washing_machine INTEGER NOT NULL DEFAULT 1")
    _safe_add_column(conn, "houses", "ADD COLUMN tumble_dryer INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN dishwasher INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN cooker INTEGER NOT NULL DEFAULT 1")
    _safe_add_column(conn, "houses", "ADD COLUMN microwave INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN coffee_maker INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN central_heating INTEGER NOT NULL DEFAULT 1")
    _safe_add_column(conn, "houses", "ADD COLUMN air_con INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN vacuum INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN fob_entry INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN garden INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN roof_terrace INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN games_room INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN cinema_room INTEGER NOT NULL DEFAULT 0")

    # --- EPC rating text (optional) ---
    _safe_add_column(conn, "houses", "ADD COLUMN epc_rating TEXT NOT NULL DEFAULT ''")

    # --- Rooms fields (2025-09-01) ---
    _safe_add_column(conn, "rooms", "ADD COLUMN price_pcm INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "rooms", "ADD COLUMN safe INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "rooms", "ADD COLUMN dressing_table INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "rooms", "ADD COLUMN mirror INTEGER NOT NULL DEFAULT 0")

    # --- Room non-searchable features (2025-09-01) ---
    _safe_add_column(conn, "rooms", "ADD COLUMN bedside_table INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "rooms", "ADD COLUMN blinds INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "rooms", "ADD COLUMN curtains INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "rooms", "ADD COLUMN sofa INTEGER NOT NULL DEFAULT 0")

    # --- Searchable room flags (couples/disabled) ---
    _safe_add_column(conn, "rooms", "ADD COLUMN couples_ok INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "rooms", "ADD COLUMN disabled_ok INTEGER NOT NULL DEFAULT 0")

    # --- Room availability (2025-09-02) ---
    _safe_add_column(conn, "rooms", "ADD COLUMN is_let INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "rooms", "ADD COLUMN available_from TEXT NOT NULL DEFAULT ''")
    _safe_add_column(conn, "rooms", "ADD COLUMN let_until TEXT NOT NULL DEFAULT ''")

    # --- Descriptions (2025-09-02) ---
    _safe_add_column(conn, "rooms", "ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    _safe_add_column(conn, "houses", "ADD COLUMN description TEXT NOT NULL DEFAULT ''")

    # --- Landlord profile media (logo & photo) ---
    _safe_add_column(conn, "landlord_profiles", "ADD COLUMN logo_path TEXT")
    _safe_add_column(conn, "landlord_profiles", "ADD COLUMN photo_path TEXT")
# --- House feature highlights (short strings) ---
    _safe_add_column(conn, "houses", "ADD COLUMN feature1 TEXT NOT NULL DEFAULT ''")
    _safe_add_column(conn, "houses", "ADD COLUMN feature2 TEXT NOT NULL DEFAULT ''")
    _safe_add_column(conn, "houses", "ADD COLUMN feature3 TEXT NOT NULL DEFAULT ''")
    _safe_add_column(conn, "houses", "ADD COLUMN feature4 TEXT NOT NULL DEFAULT ''")
    _safe_add_column(conn, "houses", "ADD COLUMN feature5 TEXT NOT NULL DEFAULT ''")
    
    print("[db] Feature highlight columns ready")





    

    # --- house_images add-only sync ---
    if table_exists(conn, "house_images"):
        _safe_add_column(conn, "house_images", "ADD COLUMN file_name TEXT NOT NULL DEFAULT ''")
        _safe_add_column(conn, "house_images", "ADD COLUMN filename TEXT NOT NULL DEFAULT ''")
        _safe_add_column(conn, "house_images", "ADD COLUMN file_path TEXT NOT NULL DEFAULT ''")
        _safe_add_column(conn, "house_images", "ADD COLUMN width INTEGER NOT NULL DEFAULT 0")
        _safe_add_column(conn, "house_images", "ADD COLUMN height INTEGER NOT NULL DEFAULT 0")
        _safe_add_column(conn, "house_images", "ADD COLUMN bytes INTEGER NOT NULL DEFAULT 0")
        _safe_add_column(conn, "house_images", "ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0")
        _safe_add_column(conn, "house_images", "ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        _safe_add_column(conn, "house_images", "ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        try:
            conn.execute("""
                UPDATE house_images
                   SET file_name = CASE
                        WHEN (file_name IS NULL OR file_name='') AND COALESCE(filename,'')!='' THEN filename
                        ELSE file_name
                   END,
                       filename = CASE
                        WHEN (filename IS NULL OR filename='') AND COALESCE(file_name,'')!='' THEN file_name
                        ELSE filename
                   END
            """)
            conn.commit()
        except Exception as e:
            print("[MIGRATE] backfill filenames:", e)

    # -------------------------------------------------------------------------
    # NEW SUMMARY / CONTROL FIELDS (your request)
    # -------------------------------------------------------------------------
    # Houses: summary counts + availability info
    _safe_add_column(conn, "houses", "ADD COLUMN ensuites_total INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN available_rooms_total INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN available_rooms_prices TEXT NOT NULL DEFAULT ''")
    _safe_add_column(conn, "houses", "ADD COLUMN double_beds_total INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN suitable_for_couples_total INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN suitable_for_disabled_total INTEGER NOT NULL DEFAULT 0")
    _safe_add_column(conn, "houses", "ADD COLUMN post_code_prefix TEXT NOT NULL DEFAULT ''")

    # Landlord profiles: admin toggle for new signups
    _safe_add_column(conn, "landlord_profiles", "ADD COLUMN enable_new_landlord INTEGER NOT NULL DEFAULT 1")

    conn.close()

# Run migrations at import
ensure_db()
