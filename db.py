# db.py
from __future__ import annotations

import os
import sqlite3
from datetime import datetime as dt
from pathlib import Path

# -----------------------------------------------------------------------------
# Resolve DB path (env var wins; then pick an existing/non-empty file)
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent

def _choose_db_path() -> str:
    # 1) Respect explicit env var
    env_path = os.environ.get("DB_PATH")
    if env_path:
        p = Path(env_path)
        print(f"[db] DB_PATH from env: {p} (exists={p.exists()} size={p.stat().st_size if p.exists() else '—'})")
        return str(p)

    # 2) Prefer uploads/student_palace.db if it exists (most likely your data)
    uploads_db = PROJECT_ROOT / "uploads" / "student_palace.db"
    root_db    = PROJECT_ROOT / "student_palace.db"

    candidates = []
    if uploads_db.exists():
        candidates.append(uploads_db)
    if root_db.exists():
        candidates.append(root_db)

    if candidates:
        # pick the larger (heuristic for "has data")
        best = max(candidates, key=lambda p: p.stat().st_size)
        print(f"[db] DB_PATH auto-selected: {best} (size={best.stat().st_size})")
        return str(best)

    # 3) Fall back to uploads path (will be created if missing)
    fallback = uploads_db
    print(f"[db] DB_PATH fallback (new): {fallback}")
    return str(fallback)

DB_PATH = _choose_db_path()

# Ensure containing folder exists (for new DBs only)
db_dir = Path(DB_PATH).parent
db_dir.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# Connection helper
# -----------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return conn

# -----------------------------------------------------------------------------
# Small helpers
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
    Add a column with ALTER TABLE if it's missing.
    Example ddl: "ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
    """
    try:
        after = ddl.strip().split("ADD COLUMN", 1)[1].strip()
        col_name = after.split()[0]
        if not table_has_column(conn, table, col_name):
            conn.execute(f"ALTER TABLE {table} {ddl}")
            conn.commit()
    except Exception as e:
        print(f"[MIGRATE] Skipped '{ddl}' on {table}: {e}")

# -----------------------------------------------------------------------------
# Schema bootstrap + non-destructive migrations
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

    conn.close()

# Run migrations at import so other modules can rely on schema existing
ensure_db()
