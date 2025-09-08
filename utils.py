from flask import session, redirect, url_for, flash, request
from db import get_db
from datetime import datetime  # <-- added

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

# -------------------------------------------------
# Academic year helper (for property + search views)
# Academic year runs 1 July -> 30 June (e.g. 2025/2026)
# -------------------------------------------------
def get_academic_year_label(rooms):
    """
    Derive one or more academic year labels from a house's rooms.
    Returns a comma-separated string like "2025/2026, 2026/2027" or None.
    Expects room date strings in '%Y-%m-%d'.
    """
    if not rooms:
        return None

    fmt = "%Y-%m-%d"
    labels = set()

    for r in rooms:
        try:
            start_raw = r.get("available_from") if isinstance(r, dict) else r["available_from"]
            end_raw = r.get("let_until") if isinstance(r, dict) else r["let_until"]
            if not start_raw:
                continue

            start = datetime.strptime(start_raw, fmt)
            end = datetime.strptime(end_raw, fmt) if (end_raw or "").strip() else None

            # Primary year from available_from
            start_year = start.year if start.month >= 7 else (start.year - 1)
            labels.add(f"{start_year}/{start_year + 1}")

            # If the let_until crosses into a (same or another) academic year, include that too
            if end:
                end_year = end.year if end.month >= 7 else (end.year - 1)
                labels.add(f"{end_year}/{end_year + 1}")
        except Exception:
            # Skip malformed rows silently
            continue

    return ", ".join(sorted(labels)) if labels else None
