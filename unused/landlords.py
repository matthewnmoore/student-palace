# admin/landlords.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from models import get_db
from . import bp, _is_admin


def _ensure_landlord_profiles_table(conn) -> None:
    """
    Create landlord_profiles if it doesn't exist.
    Safe to call on every request.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS landlord_profiles (
            landlord_id   INTEGER PRIMARY KEY,
            display_name  TEXT,
            public_slug   TEXT UNIQUE,
            phone         TEXT,
            website       TEXT,
            bio           TEXT,
            profile_views INTEGER NOT NULL DEFAULT 0,
            is_verified   INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (landlord_id) REFERENCES landlords(id) ON DELETE CASCADE
        );
    """)


# -------------------------
# List + search landlords
# -------------------------
@bp.route("/landlords", methods=["GET"])
def admin_landlords():
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    q = (request.args.get("q") or "").strip().lower()
    conn = get_db()
    try:
        _ensure_landlord_profiles_table(conn)

        if q:
            rows = conn.execute("""
                SELECT l.id,
                       l.email,
                       l.created_at,
                       COALESCE(p.display_name,'') AS display_name,
                       COALESCE(p.public_slug,'')  AS public_slug,
                       COALESCE(p.profile_views,0) AS profile_views,
                       COALESCE(p.is_verified,0)   AS is_verified
                  FROM landlords l
             LEFT JOIN landlord_profiles p ON p.landlord_id = l.id
                 WHERE LOWER(l.email) LIKE ? OR LOWER(COALESCE(p.display_name,'')) LIKE ?
              ORDER BY l.created_at DESC
            """, (f"%{q}%", f"%{q}%")).fetchall()
        else:
            rows = conn.execute("""
                SELECT l.id,
                       l.email,
                       l.created_at,
                       COALESCE(p.display_name,'') AS display_name,
                       COALESCE(p.public_slug,'')  AS public_slug,
                       COALESCE(p.profile_views,0) AS profile_views,
                       COALESCE(p.is_verified,0)   AS is_verified
                  FROM landlords l
             LEFT JOIN landlord_profiles p ON p.landlord_id = l.id
              ORDER BY l.created_at DESC
            """).fetchall()

        return render_template("admin_landlords.html", landlords=rows, q=q)
    finally:
        conn.close()


# -----------------------------------------
# Landlord detail / edit / actions / delete
# -----------------------------------------
@bp.route("/landlord/<int:lid>", methods=["GET", "POST"])
def admin_landlord_detail(lid: int):
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_db()
    try:
        _ensure_landlord_profiles_table(conn)

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()

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
                    except Exception:
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

            elif action == "set_verified":
                # Ensure profile row exists, then set flag from checkbox
                conn.execute(
                    "INSERT OR IGNORE INTO landlord_profiles(landlord_id) VALUES(?)",
                    (lid,)
                )
                is_verified = 1 if request.form.get("is_verified") == "on" else 0
                conn.execute(
                    "UPDATE landlord_profiles SET is_verified=? WHERE landlord_id=?",
                    (is_verified, lid)
                )
                conn.commit()
                flash("Verification status updated.", "ok")

            elif action == "update_profile":
                display_name = (request.form.get("display_name") or "").strip()
                phone        = (request.form.get("phone") or "").strip()
                website      = (request.form.get("website") or "").strip()
                bio          = (request.form.get("bio") or "").strip()

                # Ensure profile row exists
                conn.execute(
                    "INSERT OR IGNORE INTO landlord_profiles(landlord_id) VALUES(?)",
                    (lid,)
                )
                prof = conn.execute(
                    "SELECT * FROM landlord_profiles WHERE landlord_id=?",
                    (lid,)
                ).fetchone()

                # Auto-generate slug if missing and we have a display name
                slug = prof["public_slug"] if prof else None
                if not slug and display_name:
                    s = display_name.lower()
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

            elif action == "delete_landlord":
                # Cascade delete: profile, then landlord
                conn.execute("DELETE FROM landlord_profiles WHERE landlord_id=?", (lid,))
                conn.execute("DELETE FROM landlords WHERE id=?", (lid,))
                conn.commit()
                flash("Landlord deleted.", "ok")
                return redirect(url_for("admin.admin_landlords"))

        # GET (or after POST updates)
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
