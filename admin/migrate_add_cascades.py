# admin/migrate_add_cascades.py
from __future__ import annotations
import sqlite3, contextlib
from db import get_db

def _fk_on(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")

def _fk_off(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")

def _table_cols(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [ (r["name"] if isinstance(r, sqlite3.Row) else r[1]) for r in rows ]

def _has_fk_cascade(conn: sqlite3.Connection, table: str, fk_col: str, ref_table: str) -> bool:
    # Inspect PRAGMA foreign_key_list(table)
    try:
        rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    except sqlite3.OperationalError:
        return False
    for r in rows:
        # row fields vary by driver; handle tuple or Row
        d = dict(zip(
            ["id","seq","table","from","to","on_update","on_delete","match"],
            [r[k] if isinstance(r, sqlite3.Row) else r[k] for k in range(len(r))]
        )) if not isinstance(r, sqlite3.Row) else r
        tbl = d["table"] if isinstance(d, dict) else r["table"]
        frm = d["from"]  if isinstance(d, dict) else r["from"]
        ondel = d["on_delete"] if isinstance(d, dict) else r["on_delete"]
        if tbl == ref_table and frm == fk_col and str(ondel).lower() == "cascade":
            return True
    return False

def _rebuild_rooms(conn: sqlite3.Connection):
    if not _has_fk_cascade(conn, "rooms", "house_id", "houses"):
        _rebuild_with_cascade(
            conn,
            table="rooms",
            create_sql="""
                CREATE TABLE rooms_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    house_id INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
                    FOREIGN KEY (house_id) REFERENCES houses(id) ON DELETE CASCADE
                );
            """,
            copy_cols=["id","house_id","title","created_at"],
        )

def _rebuild_house_images(conn: sqlite3.Connection):
    if not _has_fk_cascade(conn, "house_images", "house_id", "houses"):
        _rebuild_with_cascade(
            conn,
            table="house_images",
            create_sql="""
                CREATE TABLE house_images_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    house_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    bytes INTEGER NOT NULL,
                    is_primary INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    FOREIGN KEY (house_id) REFERENCES houses(id) ON DELETE CASCADE
                );
            """,
            copy_cols=["id","house_id","file_name","file_path","width","height","bytes",
                       "is_primary","sort_order","created_at","filename"],
        )

def _rebuild_house_floorplans(conn: sqlite3.Connection):
    if not _has_fk_cascade(conn, "house_floorplans", "house_id", "houses"):
        _rebuild_with_cascade(
            conn,
            table="house_floorplans",
            create_sql="""
                CREATE TABLE house_floorplans_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    house_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    bytes INTEGER NOT NULL,
                    is_primary INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    FOREIGN KEY (house_id) REFERENCES houses(id) ON DELETE CASCADE
                );
            """,
            copy_cols=["id","house_id","file_name","file_path","width","height","bytes",
                       "is_primary","sort_order","created_at","filename"],
        )

def _rebuild_room_images(conn: sqlite3.Connection):
    if not _has_fk_cascade(conn, "room_images", "room_id", "rooms"):
        _rebuild_with_cascade(
            conn,
            table="room_images",
            create_sql="""
                CREATE TABLE room_images_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    bytes INTEGER NOT NULL,
                    is_primary INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
                );
            """,
            copy_cols=["id","room_id","file_name","file_path","width","height","bytes",
                       "is_primary","sort_order","created_at","filename"],
        )

def _rebuild_with_cascade(conn: sqlite3.Connection, *, table: str, create_sql: str, copy_cols: list[str]) -> None:
    existing_cols = set(_table_cols(conn, table))
    missing = [c for c in copy_cols if c not in existing_cols]
    if missing:
        # If columns missing, we still proceed but only copy intersecting columns
        copy_cols = [c for c in copy_cols if c in existing_cols]

    _fk_off(conn)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(create_sql)
        cols_csv = ",".join(copy_cols)
        conn.execute(f"INSERT INTO {table}_new ({cols_csv}) SELECT {cols_csv} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _fk_on(conn)

def migrate() -> None:
    conn = get_db()
    try:
        conn.row_factory = sqlite3.Row
        _fk_on(conn)
        with contextlib.ExitStack():
            _rebuild_rooms(conn)
            _rebuild_house_images(conn)
            _rebuild_house_floorplans(conn)
            _rebuild_room_images(conn)
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    migrate()
    print("✅ Migration complete: cascades ensured.")
