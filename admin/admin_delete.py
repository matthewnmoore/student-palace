# admin/admin_delete.py
from __future__ import annotations
from flask import render_template, redirect, url_for, flash
from db import get_db
from . import bp, _is_admin

@bp.get("/landlords/<int:lid>/delete", endpoint="admin_landlord_delete_ask1")
def admin_landlord_delete_ask1(lid: int):
    """Step 1: show the first confirmation screen (no deletion yet)."""
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_db()
    try:
        ll = conn.execute(
            "SELECT id, email FROM landlords WHERE id=?", (lid,)
        ).fetchone()
        if not ll:
            flash("Landlord not found.", "error")
            return redirect(url_for("admin.admin_landlords"))

        # (Nice, but optional) show how many houses they own
        stats = conn.execute(
            "SELECT COUNT(*) AS houses FROM houses WHERE landlord_id=?", (lid,)
        ).fetchone()
        houses_count = int(stats["houses"] if stats else 0)

        return render_template(
            "admin_landlord_delete_ask.html",
            landlord=ll,
            houses_count=houses_count,
            step="ask1",
        )
    finally:
        conn.close()
