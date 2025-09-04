# admin/summaries.py
from __future__ import annotations

import sqlite3
from flask import render_template, redirect, url_for, flash
from models import get_db
from . import bp, _is_admin

# Optional: use your real utility if present
try:
    import utils_summaries  # must expose recompute_all_houses(conn)
except Exception:
    utils_summaries = None


def _fetch_totals(conn: sqlite3.Connection) -> dict:
    houses = conn.execute("SELECT COUNT(*) FROM houses").fetchone()[0] or 0
    bedrooms = conn.execute(
        "SELECT COALESCE(SUM(bedrooms_total), 0) FROM houses"
    ).fetchone()[0] or 0
    rooms_created = conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] or 0
    rooms_available = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN is_let = 0 THEN 1 ELSE 0 END), 0) FROM rooms"
    ).fetchone()[0] or 0
    return {
        "houses": houses,
        "bedrooms": bedrooms,
        "rooms_created": rooms_created,
        "rooms_available": rooms_available,
    }


def _fetch_houses(conn: sqlite3.Connection):
    """
    Per-house rollups for the table.
    LEFT JOIN ensures houses with zero rooms still appear.
    Also returns precomputed columns stored on houses:
      - ensuites_total
      - double_beds_total
      - suitable_for_couples_total
    """
    rows = conn.execute(
        """
        SELECT
          h.id,
          h.title,
          h.city,
          h.bedrooms_total,
          COALESCE(COUNT(r.id), 0)                                        AS rooms_created,
          COALESCE(SUM(CASE WHEN r.is_let = 0 THEN 1 ELSE 0 END), 0)       AS rooms_available,
          COALESCE(h.ensuites_total, 0)                                    AS ensuites_total,
          COALESCE(h.double_beds_total, 0)                                 AS double_beds_total,
          COALESCE(h.suitable_for_couples_total, 0)                        AS suitable_for_couples_total
        FROM houses h
        LEFT JOIN rooms r ON r.house_id = h.id
        GROUP BY h.id
        ORDER BY h.city ASC, h.title ASC, h.id ASC
        """
    ).fetchall()
    return rows


@bp.route("/summaries")
def admin_summaries():
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_db()
    try:
        totals = _fetch_totals(conn)
        houses = _fetch_houses(conn)
        return render_template("admin_summaries.html", totals=totals, houses=houses)
    finally:
        conn.close()


@bp.route("/summaries/recompute")
def admin_summaries_recompute():
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_db()
    try:
        if utils_summaries and hasattr(utils_summaries, "recompute_all_houses"):
            utils_summaries.recompute_all_houses(conn)
            conn.commit()
            flash("Recomputed summaries for all houses.", "ok")
        else:
            flash("Recompute utility not found; nothing changed.", "error")
    finally:
        conn.close()

    return redirect(url_for("admin.admin_summaries"))
