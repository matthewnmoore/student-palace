# admin/db_report.py
from __future__ import annotations

import sqlite3
from flask import render_template
from db import get_db
from . import bp, require_admin

def _tables(conn: sqlite3.Connection):
    # All user tables (skip sqlite_internal)
    return conn.execute("""
        SELECT name, type
          FROM sqlite_master
         WHERE type IN ('table','view')
           AND name NOT LIKE 'sqlite_%'
         ORDER BY name
    """).fetchall()

def _columns(conn: sqlite3.Connection, table: str):
    # PRAGMA table_info gives: cid, name, type, notnull, dflt_value, pk
    return conn.execute(f"PRAGMA table_info({table})").fetchall()

def _indexes(conn: sqlite3.Connection, table: str):
    try:
        idx = conn.execute(f"PRAGMA index_list({table})").fetchall()
        out = []
        for r in idx or []:
            idx_name = r["name"]
            cols = conn.execute(f"PRAGMA index_info({idx_name})").fetchall()
            out.append({"name": idx_name, "unique": bool(r["unique"]), "cols": cols})
        return out
    except Exception:
        return []

def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        return int(row["c"] if row else 0)
    except Exception:
        return 0

def _first_row_as_dict(conn: sqlite3.Connection, table: str) -> dict:
    try:
        cols = [c["name"] for c in _columns(conn, table)]
        if not cols:
            return {}
        row = conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchone()
        if not row:
            # Return empty values for known columns (so UI can still show structure)
            return {k: "" for k in cols}
        return {k: row[k] for k in cols}
    except Exception:
        return {}

@bp.get("/db-report", endpoint="db_report")
def admin_db_report():
    """Read-only overview of tables, columns and counts."""
    r = require_admin()
    if r:
        return r

    conn = get_db()
    try:
        tbls = _tables(conn)
        report = []
        for t in tbls:
            name = t["name"]
            info = {
                "name": name,
                "type": t["type"],
                "count": _count(conn, name) if t["type"] == "table" else "n/a",
                "columns": _columns(conn, name),
                "indexes": _indexes(conn, name) if t["type"] == "table" else [],
            }
            report.append(info)

        # site_settings (generic: show whatever columns exist, first row)
        site_settings = {}
        if any(r["name"] == "site_settings" and r["type"] == "table" for r in tbls):
            site_settings = _first_row_as_dict(conn, "site_settings")

        # Quick totals for common tables if present
        quick_totals = {}
        for tname in ("landlords", "houses", "rooms", "house_images", "students"):
            if any(t["name"] == tname and t["type"] == "table" for t in tbls):
                quick_totals[tname] = _count(conn, tname)

        return render_template(
            "admin_db_report.html",
            report=report,
            quick_totals=quick_totals,
            site_settings=site_settings,
        )
    finally:
        conn.close()
