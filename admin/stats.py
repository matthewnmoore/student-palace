# admin/stats.py
from __future__ import annotations

import math
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils_summaries import recompute_all_houses

# Import from the admin package so routes register on the admin blueprint
from . import bp, require_admin


# -----------------------
# Helpers (local)
# -----------------------
def _parse_int(name: str, default: int, min_val: int = 1, max_val: int | None = None) -> int:
    try:
        v = int(request.args.get(name, default))
    except Exception:
        v = default
    if v < min_val:
        v = min_val
    if max_val is not None and v > max_val:
        v = max_val
    return v


# -----------------------
# Pages
# -----------------------

# Endpoint name MUST be 'dashboard' so url_for('admin.dashboard') works
@bp.get("/dashboard", endpoint="dashboard")
def admin_dashboard():
    """Read-only stats dashboard at /admin/dashboard."""
    r = require_admin()
    if r:
        return r

    conn = get_db()

    # Totals
    totals = {
        "landlords": conn.execute("SELECT COUNT(*) FROM landlords").fetchone()[0],
        "houses":    conn.execute("SELECT COUNT(*) FROM houses").fetchone()[0],
        "rooms":     conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0],
    }

    # Last 24h deltas (UTC)
    deltas = {
        "landlords": conn.execute("SELECT COUNT(*) FROM landlords WHERE created_at >= datetime('now','-1 day')").fetchone()[0],
        "houses":    conn.execute("SELECT COUNT(*) FROM houses    WHERE created_at >= datetime('now','-1 day')").fetchone()[0],
        "rooms":     conn.execute("SELECT COUNT(*) FROM rooms     WHERE created_at >= datetime('now','-1 day')").fetchone()[0],
    }

    conn.close()
    return render_template("admin_dashboard.html", totals=totals, deltas=deltas)


@bp.route("/summaries")
def admin_summaries():
    """
    Admin: Live view of per-house availability rollups.
    Shows bedrooms_total, total rooms created, rooms_available (derived),
    and a quick 'status' pill.
    """
    r = require_admin()
    if r:
        return r

    page  = _parse_int("page", 1)
    limit = _parse_int("limit", 25, min_val=5, max_val=200)
    offset = (page - 1) * limit

    q = (request.args.get("q") or "").strip()

    conn = get_db()

    # Count total houses (with optional search)
    where = ""
    params = []
    if q:
        where = "WHERE h.title LIKE ? OR h.city LIKE ? OR CAST(h.id AS TEXT) LIKE ?"
        like = f"%{q}%"
        params.extend([like, like, like])

    total = conn.execute(f"SELECT COUNT(*) FROM houses h {where}", params).fetchone()[0]
    pages = max(1, math.ceil(total / limit))

    # Pull page of houses with room rollups
    sql = f"""
    SELECT
      h.id,
      h.title,
      h.city,
      h.letting_type,
      h.bedrooms_total,
      COALESCE(SUM(CASE WHEN r.id IS NOT NULL THEN 1 ELSE 0 END), 0)               AS rooms_total,
      COALESCE(SUM(CASE
         WHEN r.id IS NULL                                              THEN 0
         WHEN r.is_let IN (1, '1', 'on', 'true', 'True')                THEN 0
         ELSE 1
      END), 0) AS rooms_available,
      h.created_at
    FROM houses h
    LEFT JOIN rooms r ON r.house_id = h.id
    {where}
    GROUP BY h.id
    ORDER BY h.created_at DESC, h.id DESC
    LIMIT ? OFFSET ?
    """
    items = conn.execute(sql, (*params, limit, offset)).fetchall()

    # Totals at a glance across *all* houses (ignores search filter)
    at_a_glance = conn.execute("""
      SELECT
        COUNT(*)                                  AS houses_total,
        COALESCE(SUM(bedrooms_total), 0)          AS bedrooms_sum,
        (SELECT COUNT(*) FROM rooms)              AS rooms_total_all,
        (SELECT COALESCE(SUM(
           CASE WHEN is_let IN (1, '1', 'on', 'true', 'True') THEN 0 ELSE 1 END
        ),0) FROM rooms)                          AS rooms_available_all
      FROM houses
    """).fetchone()

    conn.close()

    return render_template(
        "admin_summaries.html",
        items=items,
        total=total,
        pages=pages,
        page=page,
        limit=limit,
        q=q,
        glance=at_a_glance
    )


@bp.route("/summaries/recompute", methods=["POST"])
def admin_summaries_recompute():
    """
    Button to recompute summaries for all houses.
    (Idempotent, uses utils_summaries.recompute_all_houses)
    """
    r = require_admin()
    if r:
        return r

    conn = get_db()
    changed = recompute_all_houses(conn)
    conn.commit()
    conn.close()

    flash(f"Recomputed summaries for {changed} houses.", "ok")
    # Preserve current list paging/search when we land back
    return redirect(url_for("admin.admin_summaries",
                            page=request.args.get("page", 1),
                            limit=request.args.get("limit", 25),
                            q=request.args.get("q", "")))
