# admin/cities.py
from __future__ import annotations

import sqlite3
from flask import render_template, request, redirect, url_for, flash
from models import get_db
from . import bp, _is_admin

@bp.route("/cities", methods=["GET", "POST"])
def admin_cities():
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_db()
    try:
        if request.method == "POST":
            action = request.form.get("action") or ""
            if action == "add":
                name = (request.form.get("name") or "").strip()
                if name:
                    try:
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS cities("
                            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                            " name TEXT UNIQUE NOT NULL,"
                            " is_active INTEGER NOT NULL DEFAULT 1)"
                        )
                        conn.execute(
                            "INSERT INTO cities(name,is_active) VALUES(?,1)", (name,)
                        )
                        conn.commit()
                        flash(f"Added city: {name}", "ok")
                    except sqlite3.IntegrityError:
                        flash("That city already exists.", "error")

            elif action in ("activate", "deactivate", "delete"):
                try:
                    cid = int(request.form.get("city_id") or 0)
                except Exception:
                    cid = 0
                if cid:
                    if action == "delete":
                        conn.execute("DELETE FROM cities WHERE id=?", (cid,))
                        conn.commit()
                        flash("City deleted.", "ok")
                    else:
                        new_val = 1 if action == "activate" else 0
                        conn.execute(
                            "UPDATE cities SET is_active=? WHERE id=?", (new_val, cid)
                        )
                        conn.commit()
                        flash("City updated.", "ok")

        rows = conn.execute(
            "SELECT * FROM cities ORDER BY name ASC"
        ).fetchall()
        return render_template("admin_cities.html", cities=rows)
    finally:
        conn.close()
