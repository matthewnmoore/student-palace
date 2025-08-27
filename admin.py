import secrets
import sqlite3
from datetime import datetime as dt
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash
)

from models import get_db

bp = Blueprint("admin", __name__, url_prefix="/admin")

# --- Helpers ---
def is_admin():
    return bool(session.get("is_admin"))

# --- Auth ---
@bp.route("/login", methods=["GET","POST"])
def login():
    import os
    ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
    if request.method == "POST":
        token = (request.form.get("token") or "").strip()
        if ADMIN_TOKEN and token == ADMIN_TOKEN:
            session["is_admin"] = True
            flash("Admin session started.", "ok")
            return redirect(url_for("admin.cities"))
        flash("Invalid admin token.", "error")
    return render_template("admin_login.html")

@bp.route("/logout")
def logout():
    session.pop("is_admin", None)
    flash("Admin logged out.", "ok")
    return redirect(url_for("public.index"))

# --- Cities ---
@bp.route("/cities", methods=["GET","POST"])
def cities():
    if not is_admin():
        return redirect(url_for("admin.login"))

    conn = get_db()
    try:
        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "add":
                name = (request.form.get("name") or "").strip()
                image_url = (request.form.get("image_url") or "").strip() or None
                if name:
                    # new city default sort_order to end of list
                    max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM cities").fetchone()[0] or 0
                    sort_order = max_order + 10
                    try:
                        conn.execute(
                            "INSERT INTO cities(name, is_active, sort_order, image_url) VALUES (?, 1, ?, ?)",
                            (name, sort_order, image_url)
                        )
                        conn.commit()
                        flash(f"Added city: {name}", "ok")
                    except sqlite3.IntegrityError:
                        flash("That city already exists.", "error")

            elif action == "update":
                try:
                    cid = int(request.form.get("city_id") or 0)
                except Exception:
                    cid = 0
                name = (request.form.get("name") or "").strip()
                image_url = (request.form.get("image_url") or "").strip() or None
                if cid and name:
                    try:
                        conn.execute(
                            "UPDATE cities SET name=?, image_url=? WHERE id=?",
                            (name, image_url, cid)
                        )
                        conn.commit()
                        flash("City updated.", "ok")
                    except sqlite3.IntegrityError:
                        flash("City name must be unique.", "error")

            elif action in ("activate", "deactivate"):
                try:
                    cid = int(request.form.get("city_id") or 0)
                except Exception:
                    cid = 0
                if cid:
                    new_val = 1 if action == "activate" else 0
                    conn.execute("UPDATE cities SET is_active=? WHERE id=?", (new_val, cid))
                    conn.commit()
                    flash("City status updated.", "ok")

            elif action == "delete":
                try:
                    cid = int(request.form.get("city_id") or 0)
                except Exception:
                    cid = 0
                if cid:
                    conn.execute("DELETE FROM cities WHERE id=?", (cid,))
                    conn.commit()
                    flash("City deleted.", "ok")

            elif action in ("move_up", "move_down"):
                try:
                    cid = int(request.form.get("city_id") or 0)
                except Exception:
                    cid = 0
                if cid:
                    # fetch this city
                    row = conn.execute("SELECT id, sort_order FROM cities WHERE id=?", (cid,)).fetchone()
                    if row:
                        direction = -15 if action == "move_up" else 15
                        new_order = (row["sort_order"] or 1000) + direction
                        conn.execute("UPDATE cities SET sort_order=? WHERE id=?", (new_order, cid))
                        conn.commit()
                        # normalize gaps to keep ordering stable
                        _normalize_city_order(conn)
                        flash("City reordered.", "ok")

        rows = conn.execute("""
            SELECT * FROM cities
            ORDER BY sort_order ASC, name ASC
        """).fetchall()
        return render_template("admin_cities.html", cities=rows)
    finally:
        conn.close()

def _normalize_city_order(conn):
    rows = conn.execute("SELECT id FROM cities ORDER BY sort_order ASC, name ASC").fetchall()
    order = 10
    for r in rows:
        conn.execute("UPDATE cities SET sort_order=? WHERE id=?", (order, r["id"]))
        order += 10
    conn.commit()
