from flask import session, redirect, url_for, flash, request
from db import get_db

def is_admin():
    return bool(session.get("is_admin"))

def current_landlord_id():
    return session.get("landlord_id")

def require_landlord():
    if not current_landlord_id():
        flash("Please log in to continue.", "error")
        return redirect(url_for("auth.login"))
    return None

def slugify(name: str) -> str:
    s = (name or "").strip().lower()
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    slug = "".join(out).strip("-")
    return slug or "landlord"

def get_active_cities_safe():
    try:
        conn = get_db()
        rows = conn.execute("SELECT name FROM cities WHERE is_active=1 ORDER BY name ASC").fetchall()
        conn.close()
        return [r["name"] for r in rows]
    except Exception:
        return []

def validate_city_active(city):
    if not city:
        return False
    conn = get_db()
    row = conn.execute("SELECT 1 FROM cities WHERE name=? AND is_active=1", (city,)).fetchone()
    conn.close()
    return bool(row)

def clean_bool(field_name):
    return 1 if (request.form.get(field_name) == "on") else 0

def valid_choice(value, choices):
    return value in choices

def owned_house_or_none(conn, hid, landlord_id):
    return conn.execute("SELECT * FROM houses WHERE id=? AND landlord_id=?", (hid, landlord_id)).fetchone()
