# admin.py
import os
import sqlite3
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, current_app
)
from werkzeug.security import generate_password_hash
from datetime import datetime as dt

# Pull DB helpers from your shared module
from models import get_db

# ---------------------------------
# Blueprint
# ---------------------------------
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Small helper
def _is_admin() -> bool:
    return bool(session.get("is_admin"))

def _admin_token() -> str:
    return (current_app.config.get("ADMIN_TOKEN")
            or os.environ.get("ADMIN_TOKEN", ""))

# ---------------------------------
# Auth
# ---------------------------------
@admin_bp.route("/login", methods=["GET", "POST"])
def admin_login():
    try:
        if request.method == "POST":
            token = (request.form.get("token") or "").strip()
            if _admin_token() and token == _admin_token():
                session["is_admin"] = True
                flash("Admin session started.", "ok")
                return redirect(url_for("admin.admin_cities"))
            flash("Invalid admin token.", "error")
        return render_template("admin_login.html")
    except Exception as e:
        current_app.logger.error("admin_login: %s", e)
        flash("Admin login error.", "error")
        return redirect(url_for("public.index"))

@admin_bp.route("/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.", "ok")
    return redirect(url_for("public.index"))

# ---------------------------------
# Cities
# ---------------------------------
@admin_bp.route("/cities", methods=["GET", "POST"])
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
                            " is_active INTEGER NOT NULL DEFAULT 1"
                            ");"
                        )
                        conn.execute(
                            "INSERT INTO cities(name,is_active) VALUES(?,1)",
                            (name,)
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
                            "UPDATE cities SET is_active=? WHERE id=?",
                            (new_val, cid)
                        )
                        conn.commit()
                        flash("City updated.", "ok")

        rows = conn.execute(
            "SELECT * FROM cities ORDER BY name ASC"
        ).fetchall()
        return render_template("admin_cities.html", cities=rows)
    finally:
        conn.close()

# ---------------------------------
# Landlords list
# ---------------------------------
@admin_bp.route("/landlords", methods=["GET"])
def admin_landlords():
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    q = (request.args.get("q") or "").strip().lower()
    conn = get_db()
    try:
        if q:
            rows = conn.execute("""
                SELECT l.id, l.email, l.created_at, l.is_verified,
                       COALESCE(p.display_name,'') AS display_name,
                       COALESCE(p.public_slug,'') AS public_slug,
                       COALESCE(p.profile_views,0) AS profile_views
                FROM landlords l
                LEFT JOIN landlord_profiles p ON p.landlord_id = l.id
                WHERE LOWER(l.email) LIKE ? OR LOWER(COALESCE(p.display_name,'')) LIKE ?
                ORDER BY l.created_at DESC
            """, (f"%{q}%", f"%{q}%")).fetchall()
        else:
            rows = conn.execute("""
                SELECT l.id, l.email, l.created_at, l.is_verified,
                       COALESCE(p.display_name,'') AS display_name,
                       COALESCE(p.public_slug,'') AS public_slug,
                       COALESCE(p.profile_views,0) AS profile_views
                FROM landlords l
                LEFT JOIN landlord_profiles p ON p.landlord_id = l.id
                ORDER BY l.created_at DESC
            """).fetchall()
        return render_template("admin_landlords.html", landlords=rows, q=q)
    finally:
        conn.close()

# ---------------------------------
# Landlord detail / edit / delete
# ---------------------------------
@admin_bp.route("/landlord/<int:lid>", methods=["GET", "POST"])
def admin_landlord_detail(lid: int):
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_db()
    try:
        if request.method == "POST":
            action = request.form.get("action") or ""

            if action == "update_email":
                new_email = (request.form.get("email") or "").strip().lower()
                if new_email:
                    try:
                        conn.execute(
                            "UPDATE landlords SET email=? WHERE id=?",
                            (new_email, lid)
                        )
                        conn.commit()
                        flash("Email updated.", "ok")
                    except sqlite3.IntegrityError:
                        flash("That email is already taken.", "error")

            elif action == "reset_password":
                new_pw = (request.form.get("new_password") or "").strip()
                if not new_pw:
                    import secrets
                    new_pw = secrets.token_urlsafe(8)
                    flash(f"Generated temporary password: {new_pw}", "ok")
                ph = generate_password_hash(new_pw)
                conn.execute(
                    "UPDATE landlords SET password_hash=? WHERE id=?",
                    (ph, lid)
                )
                conn.commit()
                flash("Password reset.", "ok")

            elif action == "update_profile":
                display_name = (request.form.get("display_name") or "").strip()
                phone = (request.form.get("phone") or "").strip()
                website = (request.form.get("website") or "").strip()
                bio = (request.form.get("bio") or "").strip()

                conn.execute(
                    "INSERT OR IGNORE INTO landlord_profiles(landlord_id)"
                    " VALUES(?)",
                    (lid,)
                )
                prof = conn.execute(
                    "SELECT * FROM landlord_profiles WHERE landlord_id=?",
                    (lid,)
                ).fetchone()

                slug = prof["public_slug"] if prof else None
                if not slug and display_name:
                    s = (display_name or "").strip().lower()
                    out = []
                    for ch in s:
                        if ch.isalnum():
                            out.append(ch)
                        elif ch in " -_":
                            out.append("-")
                    base = "".join(out).strip("-") or "landlord"
                    candidate = base
                    i = 2
                    while conn.execute(
                        "SELECT 1 FROM landlord_profiles WHERE public_slug=?",
                        (candidate,)
                    ).fetchone():
                        candidate = f"{base}-{i}"
                        i += 1
                    slug = candidate

                conn.execute("""
                    UPDATE landlord_profiles
                       SET display_name=?,
                           phone=?,
                           website=?,
                           bio=?,
                           public_slug=COALESCE(?, public_slug)
                     WHERE landlord_id=?
                """, (display_name, phone, website, bio, slug, lid))
                conn.commit()
                flash("Profile updated.", "ok")

            elif action == "toggle_verified":
                landlord = conn.execute(
                    "SELECT is_verified FROM landlords WHERE id=?",
                    (lid,)
                ).fetchone()
                new_val = 0 if landlord and landlord["is_verified"] else 1
                conn.execute(
                    "UPDATE landlords SET is_verified=? WHERE id=?",
                    (new_val, lid)
                )
                conn.commit()
                flash("Verification status updated.", "ok")

            elif action == "delete_landlord":
                conn.execute("DELETE FROM landlord_profiles WHERE landlord_id=?", (lid,))
                conn.execute("DELETE FROM landlords WHERE id=?", (lid,))
                conn.commit()
                flash("Landlord deleted.", "ok")
                return redirect(url_for("admin.admin_landlords"))

        landlord = conn.execute(
            "SELECT * FROM landlords WHERE id=?", (lid,)
        ).fetchone()
        profile = conn.execute(
            "SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)
        ).fetchone()
        houses = conn.execute(
            "SELECT * FROM houses WHERE landlord_id=? ORDER BY created_at DESC",
            (lid,)
        ).fetchall()

        return render_template(
            "admin_landlord_view.html",
            landlord=landlord, profile=profile, houses=houses
        )
    finally:
        conn.close()
