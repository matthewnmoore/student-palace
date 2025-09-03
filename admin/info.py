# admin/info.py
from __future__ import annotations

import math
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from . import bp, require_admin
from utils_summaries import recompute_all_houses

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

@bp.route("/info", endpoint="admin_info")
def admin_info():
    """
    Admin · Website info: high-level totals + per-house room rollups.
    URL: /admin/info
    """
    r = require_admin()
    if r:
        return r

    page  = _parse_int("page", 1)
    limit = _parse_int("limit", 25, min_val=5, max_val=200)
    offset = (page - 1) * limit
    q = (request.args.get("q") or "").strip()

    conn = get_db()

    # At-a-glance totals
    glance = {
        "landlords_total": conn.execute("SELECT COUNT(*) FROM landlords").fetchone()[0],
        "houses_total":    conn.execute("SELECT COUNT(*) FROM houses").fetchone()[0],
        "rooms_total":     conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0],
        "rooms_available": conn.execute("""
            SELECT COALESCE(SUM(CASE
                WHEN is_let IN (1, '1', 'on', 'true', 'True') THEN 0 ELSE 1
            END),0)
            FROM rooms
        """).fetchone()[0],
    }

    # Search
    where = ""
    params = []
    if q:
        where = "WHERE h.title LIKE ? OR h.city LIKE ? OR CAST(h.id AS TEXT) LIKE ?"
        like = f"%{q}%"
        params.extend([like, like, like])

    total = conn.execute(f"SELECT COUNT(*) FROM houses h {where}", params).fetchone()[0]
    pages = max(1, math.ceil(total / limit))

    # Per-house rollups
    sql = f"""
    SELECT
      h.id,
      h.title,
      h.city,
      h.letting_type,
      h.bedrooms_total,
      COALESCE(SUM(CASE WHEN r.id IS NOT NULL THEN 1 ELSE 0 END), 0) AS rooms_total,
      COALESCE(SUM(CASE
         WHEN r.id IS NULL                                          THEN 0
         WHEN r.is_let IN (1, '1', 'on', 'true', 'True')            THEN 0
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

    conn.close()

    return render_template(
        "admin_info.html",
        glance=glance,
        items=items,
        total=total,
        pages=pages,
        page=page,
        limit=limit,
        q=q,
    )

@bp.route("/info/recompute", methods=["POST"], endpoint="admin_info_recompute")
def admin_info_recompute():
    """
    Recompute summaries for all houses (idempotent).
    Returns to the same /admin/info list preserving paging/search.
    """
    r = require_admin()
    if r:
        return r

    conn = get_db()
    changed = recompute_all_houses(conn)
    conn.commit()
    conn.close()

    flash(f"Recomputed summaries for {changed} houses.", "ok")
    return redirect(url_for("admin.admin_info",
                            page=request.args.get("page", 1),
                            limit=request.args.get("limit", 25),
                            q=request.args.get("q", "")))
