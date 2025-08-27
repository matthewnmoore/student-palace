from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash
import secrets
from config import ADMIN_TOKEN, ADMIN_DEBUG
from utils import is_admin, slugify
from db import get_db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

@admin_bp.route("/login", methods=["GET","POST"])
def admin_login():
    try:
        if request.method == "POST":
            token = (request.form.get("token") or "").strip()
            if ADMIN_TOKEN and token == ADMIN_TOKEN:
                from flask import session
                session["is_admin"] = True
                flash("Admin session started.", "ok")
                return redirect(url_for("admin.admin_cities"))
            flash("Invalid admin token.", "error")
        return render_template("admin_login.html")
    except Exception as e:
        print("[ERROR] admin_login:", e)
        flash("Admin login error.", "error")
        return redirect(url_for("public.index"))

@admin_bp.route("/logout")
def admin_logout():
    from flask import session
    session.pop("is_admin", None)
    flash("Admin logged out.", "ok")
    return redirect(url_for("public.index"))

@admin_bp.route("/ping")
def admin_ping():
    if not is_admin():
        return "not-admin", 403
    return "admin-ok", 200

# Cities
@admin_bp.route("/cities", methods=["GET","POST"])
def admin_cities():
    if not is_admin():
        return redirect(url_for("admin.admin_login"))
    conn = get_db()
    try:
        if request.method == "POST":
            action = request.form.get("action") or ""
            if action == "add":
                name = (request.form.get("name") or "").strip()
                if name:
                    try:
                        conn.execute("INSERT INTO cities(name,is_active) VALUES(?,1)", (name,))
                        conn.commit()
                        flash(f"Added city: {name}", "ok")
                    except Exception:
                        flash("That city already exists.", "error")
            elif action in ("activate","deactivate","delete"):
                try:
                    cid = int(request.form.get("city_id"))
                except Exception:
                    cid = 0
                if cid:
                    if action == "delete":
                        conn.execute("DELETE FROM cities WHERE id=?", (cid,))
                        conn.commit()
                        flash("City deleted.", "ok")
                    else:
                        new_val = 1 if action == "activate" else 0
                        conn.execute("UPDATE cities SET is_active=? WHERE id=?", (new_val, cid))
                        conn.commit()
                        flash("City updated.", "ok")
        rows = conn.execute("SELECT * FROM cities ORDER BY name ASC").fetchall()
        return render_template("admin_cities.html", cities=rows)
    finally:
        conn.close()

# Landlords list + search
@admin_bp.route("/landlords", methods=["GET"])
def admin_landlords():
    if not is_admin():
        return redirect(url_for("admin.admin_login"))
    q = (request.args.get("q") or "").strip().lower()
    conn = get_db()
    try:
        if q:
            rows = conn.execute("""
                SELECT l.id, l.email, l.created_at,
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
                SELECT l.id, l.email, l.created_at,
                       COALESCE(p.display_name,'') AS display_name,
                       COALESCE(p.public_slug,'') AS public_slug,
                       COALESCE(p.profile_views,0) AS profile_views
                FROM landlords l
                LEFT JOIN landlord_profiles p ON p.landlord_id = l.id
                ORDER BY l.created_at DESC
            """).fetchall()
        return render_template("admin_landlords.html", landlords=rows, q=q)
    except Exception as e:
        print("[ERROR] admin_landlords:", e)
        if ADMIN_DEBUG:
            return f"admin_landlords error: {e}", 500
        raise
    finally:
        conn.close()

# Landlord detail
@admin_bp.route("/landlord/<int:lid>", methods=["GET","POST"])
def admin_landlord_detail(lid):
    if not is_admin():
        return redirect(url_for("admin.admin_login"))
    conn = get_db()
    try:
        if request.method == "POST":
            action = request.form.get("action") or ""
            if action == "update_email":
                new_email = (request.form.get("email") or "").strip().lower()
                if new_email:
                    try:
                        conn.execute("UPDATE landlords SET email=? WHERE id=?", (new_email, lid))
                        conn.commit()
                        flash("Email updated.", "ok")
                    except Exception:
                        flash("That email is already taken.", "error")
            elif action == "reset_password":
                new_pw = (request.form.get("new_password") or "").strip()
                if not new_pw:
                    new_pw = secrets.token_urlsafe(8)
                    flash(f"Generated temporary password: {new_pw}", "ok")
                ph = generate_password_hash(new_pw)
                conn.execute("UPDATE landlords SET password_hash=? WHERE id=?", (ph, lid))
                conn.commit()
                flash("Password reset.", "ok")
            elif action == "update_profile":
                display_name = (request.form.get("display_name") or "").strip()
                phone = (request.form.get("phone") or "").strip()
                website = (request.form.get("website") or "").strip()
                bio = (request.form.get("bio") or "").strip()
                conn.execute("INSERT OR IGNORE INTO landlord_profiles(landlord_id) VALUES(?)", (lid,))
                prof = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
                slug = prof["public_slug"]
                if not slug and display_name:
                    base = slugify(display_name)
                    candidate = base
                    i = 2
                    while conn.execute("SELECT 1 FROM landlord_profiles WHERE public_slug=?", (candidate,)).fetchone():
                        candidate = f"{base}-{i}"
                        i += 1
                    slug = candidate
                conn.execute("""
                    UPDATE landlord_profiles
                    SET display_name=?, phone=?, website=?, bio=?, public_slug=COALESCE(?, public_slug)
                    WHERE landlord_id=?
                """, (display_name, phone, website, bio, slug, lid))
                conn.commit()
                flash("Profile updated.", "ok")
            elif action == "delete_landlord":
                conn.execute("DELETE FROM landlord_profiles WHERE landlord_id=?", (lid,))
                conn.execute("DELETE FROM landlords WHERE id=?", (lid,))
                conn.commit()
                flash("Landlord deleted.", "ok")
                return redirect(url_for("admin.admin_landlords"))

        landlord = conn.execute("SELECT * FROM landlords WHERE id=?", (lid,)).fetchone()
        profile = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
        houses = conn.execute("SELECT * FROM houses WHERE landlord_id=? ORDER BY created_at DESC", (lid,)).fetchall()
        return render_template("admin_landlord_view.html",
                               landlord=landlord, profile=profile, houses=houses)
    except Exception as e:
        print("[ERROR] admin_landlord_detail:", e)
        if ADMIN_DEBUG:
            return f"admin_landlord_detail error: {e}", 500
        raise
    finally:
        conn.close()
