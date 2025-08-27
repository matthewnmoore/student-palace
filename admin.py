import os
import sqlite3
from datetime import datetime as dt
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

# We only rely on get_db from models; is_admin is defined locally here.
from models import get_db  # noqa: F401

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# -------------------------------------------------
# Local helpers
# -------------------------------------------------
def is_admin() -> bool:
    """Check admin session flag."""
    return bool(session.get("is_admin"))


def _has_column(conn, table, column):
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        cols = [r["name"] for r in cur.fetchall()]
        return column in cols
    except Exception:
        return False


def _ensure_city_columns(conn):
    """
    Make sure cities has:
      - order_index (for admin-controlled ordering)
      - image_url (for optional city image on the homepage)
    Initialize order_index for rows where it's NULL.
    """
    changed = False

    if not _has_column(conn, "cities", "order_index"):
        conn.execute("ALTER TABLE cities ADD COLUMN order_index INTEGER")
        changed = True

    if not _has_column(conn, "cities", "image_url"):
        conn.execute("ALTER TABLE cities ADD COLUMN image_url TEXT")
        changed = True

    if changed:
        conn.commit()

    # Initialize order_index (step by 10) for any rows still NULL
    cur = conn.execute("SELECT id FROM cities WHERE order_index IS NULL ORDER BY name ASC")
    rows = cur.fetchall()
    if rows:
        idx = 10
        for r in rows:
            conn.execute("UPDATE cities SET order_index=? WHERE id=?", (idx, r["id"]))
            idx += 10
        conn.commit()


def _next_order_index(conn):
    cur = conn.execute("SELECT MAX(order_index) AS m FROM cities")
    row = cur.fetchone()
    m = row["m"] if row and row["m"] is not None else 0
    return int(m) + 10


def _get_db():
    # Tiny wrapper so we can swap easily if needed
    return get_db()


def _get_admin_token():
    # Prefer models.ADMIN_TOKEN if present, otherwise env
    try:
        from models import ADMIN_TOKEN as MODELS_ADMIN_TOKEN  # type: ignore
        return MODELS_ADMIN_TOKEN
    except Exception:
        return os.environ.get("ADMIN_TOKEN", "")


# -------------------------------------------------
# Auth
# -------------------------------------------------
@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    try:
        if request.method == "POST":
            token = (request.form.get("token") or "").strip()
            if _get_admin_token() and token == _get_admin_token():
                session["is_admin"] = True
                flash("Admin session started.", "ok")
                return redirect(url_for("admin.cities"))
            flash("Invalid admin token.", "error")
        return render_template("admin_login.html")
    except Exception as e:
        print("[ERROR] admin_login:", e)
        flash("Admin login error.", "error")
        return redirect(url_for("public.index"))


@admin_bp.route("/logout")
def logout():
    session.pop("is_admin", None)
    flash("Admin logged out.", "ok")
    return redirect(url_for("public.index"))


# -------------------------------------------------
# Cities (add / activate / deactivate / delete / reorder / set image_url)
# -------------------------------------------------
@admin_bp.route("/cities", methods=["GET", "POST"])
def cities():
    if not is_admin():
        return redirect(url_for("admin.login"))

    conn = _get_db()
    try:
        _ensure_city_columns(conn)

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()

            if action == "add":
                name = (request.form.get("name") or "").strip()
                if name:
                    try:
                        oi = _next_order_index(conn)
                        conn.execute(
                            "INSERT INTO cities(name, is_active, order_index) VALUES(?, 1, ?)",
                            (name, oi),
                        )
                        conn.commit()
                        flash(f"Added city: {name}", "ok")
                    except sqlite3.IntegrityError:
                        flash("That city already exists.", "error")

            elif action in ("activate", "deactivate", "delete"):
                try:
                    cid = int(request.form.get("city_id") or "0")
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

            elif action in ("move_up", "move_down"):
                try:
                    cid = int(request.form.get("city_id") or "0")
                except Exception:
                    cid = 0
                if cid:
                    row = conn.execute(
                        "SELECT id, order_index FROM cities WHERE id=?",
                        (cid,)
                    ).fetchone()
                    if row and row["order_index"] is not None:
                        current_idx = row["order_index"]
                        if action == "move_up":
                            neighbor = conn.execute(
                                "SELECT id, order_index FROM cities "
                                "WHERE order_index < ? "
                                "ORDER BY order_index DESC LIMIT 1",
                                (current_idx,)
                            ).fetchone()
                        else:
                            neighbor = conn.execute(
                                "SELECT id, order_index FROM cities "
                                "WHERE order_index > ? "
                                "ORDER BY order_index ASC LIMIT 1",
                                (current_idx,)
                            ).fetchone()

                        if neighbor:
                            conn.execute(
                                "UPDATE cities SET order_index=? WHERE id=?",
                                (neighbor["order_index"], row["id"])
                            )
                            conn.execute(
                                "UPDATE cities SET order_index=? WHERE id=?",
                                (current_idx, neighbor["id"])
                            )
                            conn.commit()
                            flash("City reordered.", "ok")

            elif action == "update_image":
                try:
                    cid = int(request.form.get("city_id") or "0")
                except Exception:
                    cid = 0
                image_url = (request.form.get("image_url") or "").strip()
                if cid:
                    conn.execute("UPDATE cities SET image_url=? WHERE id=?", (image_url, cid))
                    conn.commit()
                    flash("City image updated.", "ok")

        rows = conn.execute(
            "SELECT * FROM cities ORDER BY order_index ASC, name ASC"
        ).fetchall()
        return render_template("admin_cities.html", cities=rows)

    finally:
        conn.close()


# -------------------------------------------------
# Landlords list + detail (unchanged behavior)
# -------------------------------------------------
@admin_bp.route("/landlords", methods=["GET"])
def landlords():
    if not is_admin():
        return redirect(url_for("admin.login"))

    q = (request.args.get("q") or "").strip().lower()
    conn = _get_db()
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
    finally:
        conn.close()


@admin_bp.route("/landlord/<int:lid>", methods=["GET","POST"])
def landlord_detail(lid):
    if not is_admin():
        return redirect(url_for("admin.login"))

    from werkzeug.security import generate_password_hash
    from models import slugify  # re-use your existing slugify

    conn = _get_db()
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
                    except sqlite3.IntegrityError:
                        flash("That email is already taken.", "error")

            elif action == "reset_password":
                import secrets
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
                return redirect(url_for("admin.landlords"))

        landlord = conn.execute("SELECT * FROM landlords WHERE id=?", (lid,)).fetchone()
        profile = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
        houses = conn.execute("SELECT * FROM houses WHERE landlord_id=? ORDER BY created_at DESC", (lid,)).fetchall()
        return render_template("admin_landlord_view.html",
                               landlord=landlord, profile=profile, houses=houses)
    finally:
        conn.close()
