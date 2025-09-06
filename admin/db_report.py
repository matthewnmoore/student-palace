# admin/db_report.py
from __future__ import annotations

import sqlite3
from flask import render_template, render_template_string
from jinja2 import TemplateNotFound
from db import get_db
from . import bp, require_admin

def _tables(conn: sqlite3.Connection):
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
    """
    Return list of indexes with metadata:
      [{'name':..., 'unique':bool, 'origin':..., 'partial':bool, 'cols':[{'seqno':..,'cid':..,'name':..}, ...]}, ...]
    """
    try:
        idx_rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
        out = []
        for r in idx_rows or []:
            idx_name = r["name"]
            # SQLite exposes these columns in index_list
            unique = bool(r["unique"]) if "unique" in r.keys() else False
            origin = r["origin"] if "origin" in r.keys() else ""
            partial = bool(r["partial"]) if "partial" in r.keys() else False
            cols = conn.execute(f"PRAGMA index_info({idx_name})").fetchall()
            out.append({
                "name": idx_name,
                "unique": unique,
                "origin": origin,
                "partial": partial,
                "cols": cols,
            })
        return out
    except Exception:
        return []

def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        return int(row["c"] if row else 0)
    except Exception:
        return 0

@bp.get("/db-report", endpoint="db_report")
def admin_db_report():
    """Read-only overview of tables, columns, indexes and counts."""
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

        settings = []
        try:
            if any(r["name"] == "site_settings" and r["type"] == "table" for r in tbls):
                settings = conn.execute("SELECT key, value FROM site_settings ORDER BY key").fetchall()
        except Exception:
            settings = []

        quick_totals = {}
        for tname in ("landlords", "houses", "rooms", "house_images", "students"):
            if any(t["name"] == tname and t["type"] == "table" for t in tbls):
                quick_totals[tname] = _count(conn, tname)

        # Try the real template first; if it's missing, render a minimal inline page.
        try:
            return render_template(
                "admin_db_report.html",
                report=report,
                quick_totals=quick_totals,
                settings=settings,
            )
        except TemplateNotFound:
            # Fallback minimal HTML so you never get a 500
            html = """
            <h1>Database report (fallback)</h1>
            <h2>Quick totals</h2>
            <ul>
            {% for k,v in quick_totals.items() %}
              <li><strong>{{ k }}</strong>: {{ v }}</li>
            {% endfor %}
            </ul>
            <h2>Tables</h2>
            <ul>
            {% for t in report %}
              <li><strong>{{ t.name }}</strong> ({{ t.type }}) — rows: {{ t.count }}</li>
            {% endfor %}
            </ul>
            """
            return render_template_string(html, report=report, quick_totals=quick_totals)
    finally:
        conn.close()
