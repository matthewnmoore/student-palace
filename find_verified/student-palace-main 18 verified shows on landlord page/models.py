# models.py
import os
import sqlite3
from datetime import datetime

# --------- Config (Render-friendly) ----------
DB_PATH = os.environ.get("DB_PATH", "/opt/uploads/student_palace.db")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/opt/uploads")

# Ensure folders exist even if a persistent disk is mounted
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)


# --------- DB helpers ----------
def get_db():
    """Return a SQLite connection with Row factory and FK enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return conn


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return any(r["name"] == column for r in cur.fetchall())
    except Exception:
        return False


def _safe_add_column(conn: sqlite3.Connection, table: str, ddl: str) -> None:
    """
    Add a column with an ALTER TABLE if it's missing.
    Example ddl: "ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 1000"
    """
    try:
        # Extract column name (after ADD COLUMN and before space or '(')
        after = ddl.strip().split("ADD COLUMN", 1)[1].strip()
        col_name = after.split()[0]
        if not _table_has_column(conn, table, col_name):
            conn.execute(f"ALTER TABLE {table} {ddl}")
            conn.commit()
    except Exception as e:
        # ALTER TABLE can fail on older SQLite builds; swallow if already present
        print(f"[MIGRATE] Could not apply '{ddl}' on {table}: {e}")


# --------- Bootstrap / Schema ----------
def ensure_db():
    conn = get_db()
    c = conn.cursor()

    # Cities (admin-managed)
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
      profile_views INTEGER NOT NULL DEFAULT 0
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

    # ---------- Non-destructive migrations ----------
    # landlords.created_at (legacy DBs)
    try:
        if not _table_has_column(conn, "landlords", "created_at"):
            conn.execute("ALTER TABLE landlords ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
            conn.commit()
            now = datetime.utcnow().isoformat()
            conn.execute("UPDATE landlords SET created_at=? WHERE created_at='' OR created_at IS NULL", (now,))
            conn.commit()
    except Exception as e:
        print("[MIGRATE] landlords.created_at:", e)

    # cities.sort_order + cities.image_url (NEW)
    _safe_add_column(conn, "cities", "ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 1000")
    _safe_add_column(conn, "cities", "ADD COLUMN image_url TEXT")

    conn.close()


# Run migrations at import time so other modules can rely on schema existing
ensure_db()


# --------- Public helpers (imported by other blueprints) ----------
def get_active_cities_safe(order_by_admin=True):
    """
    Returns a list of active city rows (sqlite3.Row) ordered by:
      - sort_order ASC, name ASC if order_by_admin
      - name ASC otherwise
    If the table/columns don't exist yet, returns [].
    """
    try:
        conn = get_db()
        if order_by_admin and _table_has_column(conn, "cities", "sort_order"):
            rows = conn.execute(
                "SELECT * FROM cities WHERE is_active=1 ORDER BY sort_order ASC, name ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cities WHERE is_active=1 ORDER BY name ASC"
            ).fetchall()
        conn.close()
        return rows
    except Exception as e:
        print("[WARN] get_active_cities_safe:", e)
        return []


def get_active_city_names(order_by_admin=True):
    """Convenience: return just the names."""
    rows = get_active_cities_safe(order_by_admin=order_by_admin)
    return [r["name"] for r in rows]


def validate_city_active(city: str) -> bool:
    if not city:
        return False
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT 1 FROM cities WHERE name=? AND is_active=1",
            (city,)
        ).fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False
