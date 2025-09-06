# auth.py  (root-level)
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime as dt
from markupsafe import escape
from db import get_db
from utils import current_landlord_id  # if you use this elsewhere

auth_bp = Blueprint("auth", __name__)

# -------------------------
# Helpers
# -------------------------
def _get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM site_settings WHERE key=?", (key,)).fetchone()
    return (row["value"] if row and row["value"] is not None else default)

def _signups_enabled(conn) -> bool:
    # honour global switch if present; default = enabled
    val = _get_setting(conn, "signups_enabled", "1")
    return str(val) == "1"

def _get_terms_html(conn) -> str:
    """
    Read admin-managed terms from site_settings.LANDLORD_TERMS_MD.
    We return basic HTML (very light conversion: line breaks -> <br>).
    If you later store real HTML, just save it as-is and we’ll serve it.
    """
    md = _get_setting(conn, "LANDLORD_TERMS_MD", "").strip()
    if not md:
        # Friendly placeholder so the modal isn't empty if admin hasn't set content yet
        md = (
            "# Terms & Conditions\n\n"
            "Please add your landlord terms in Admin → Site settings. "
            "Until then, this placeholder is shown."
        )
    # ultra-light rendering: escape then convert newlines to <br>; treat lines starting with '# ' as a heading
    lines = []
    for line in md.splitlines():
        if line.startswith("# "):
            lines.append(f"<h2>{escape(line[2:].strip())}</h2>")
        else:
            lines.append(escape(line).replace("  ", "&nbsp;&nbsp;").replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;"))
    html = "<br>".join(lines)
    return f'<div class="terms-content">{html}</div>'

# -------------------------
# Entry page
# -------------------------
@auth_bp.route("/landlords")
def landlords_entry():
    return render_template("landlords_entry.html")

# -------------------------
# Terms endpoint (for modal)
# -------------------------
@auth_bp.route("/terms/landlord", methods=["GET"])
def landlord_terms_page():
    conn = get_db()
    try:
        html = _get_terms_html(conn)
    finally:
        conn.close()
    # Return as HTML snippet (used by the modal on the signup page)
    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp

# -------------------------
# Sign up
# -------------------------
@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    conn = get_db()
    try:
        if request.method == "POST":
            # Global kill-switch for signups
            if not _signups_enabled(conn):
                flash("Signups are currently disabled. Please try again later.", "error")
                return render_template("signup.html")

            email = (request.form.get("email") or "").strip().lower()
            password = (request.form.get("password") or "")
            agreed = (request.form.get("agree_terms") == "on")

            # Basic validation
            if not email or not password:
                flash("Email and password are required.", "error")
                return render_template("signup.html")
            if "@" not in email or "." not in email.split("@")[-1]:
                flash("Please enter a valid email address.", "error")
                return render_template("signup.html")
            if len(password) < 6:
                flash("Password must be at least 6 characters long.", "error")
                return render_template("signup.html")
            if not agreed:
                flash("Please read and agree to the Terms & Conditions to continue.", "error")
                return render_template("signup.html")

            # Uniqueness check
            exists = conn.execute("SELECT id FROM landlords WHERE email=?", (email,)).fetchone()
            if exists:
                flash("That email is already registered. Try logging in.", "error")
                return render_template("signup.html")

            # Create account
            ph = generate_password_hash(password)
            conn.execute(
                "INSERT INTO landlords(email, password_hash, created_at) VALUES (?,?,?)",
                (email, ph, dt.utcnow().isoformat()),
            )
            conn.commit()

            # Create minimal profile
            row = conn.execute("SELECT id FROM landlords WHERE email=?", (email,)).fetchone()
            lid = row["id"]
            conn.execute(
                "INSERT OR IGNORE INTO landlord_profiles(landlord_id, display_name, public_slug) VALUES (?,?,?)",
                (lid, email.split('@')[0], None)
            )
            conn.commit()

            # Session
            session["landlord_id"] = lid
            flash("Welcome! Your landlord account is ready.", "ok")
            return redirect(url_for("landlord.dashboard"))

        # GET
        return render_template("signup.html")
    except Exception as e:
        print("[ERROR] signup:", e)
        flash("Sign up failed. Please try again.", "error")
        return render_template("signup.html")
    finally:
        try:
            conn.close()
        except Exception:
            pass

# -------------------------
# Log in / Log out
# -------------------------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            email = (request.form.get("email") or "").strip().lower()
            password = (request.form.get("password") or "")
            if not email or not password:
                flash("Email and password are required.", "error")
                return render_template("login.html")

            conn = get_db()
            try:
                row = conn.execute("SELECT * FROM landlords WHERE email=?", (email,)).fetchone()
            finally:
                conn.close()

            if not row or not check_password_hash(row["password_hash"], password):
                flash("Invalid email or password.", "error")
                return render_template("login.html")

            session["landlord_id"] = row["id"]
            flash("Logged in.", "ok")
            return redirect(url_for("landlord.dashboard"))

        except Exception as e:
            print("[ERROR] login:", e)
            flash("Login failed. Please try again.", "error")
            return render_template("login.html")

    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "ok")
    return redirect(url_for("public.index"))
