from datetime import datetime as dt
from flask import render_template
from db import get_db
from utils import current_landlord_id
from . import bp

@bp.route("/dashboard")
def dashboard():
    lid = current_landlord_id()
    if not lid:
        return render_template("dashboard.html", landlord=None, profile=None)

    conn = get_db()
    landlord = conn.execute(
        "SELECT id,email,created_at FROM landlords WHERE id=?", (lid,)
    ).fetchone()
    profile = conn.execute(
        "SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)
    ).fetchone()
    houses = conn.execute(
        "SELECT * FROM houses WHERE landlord_id=? ORDER BY created_at DESC", (lid,)
    ).fetchall()
    conn.close()

    # UK date for “Member since”
    try:
        created_at_uk = dt.fromisoformat(landlord["created_at"]).strftime("%d %B %Y")
    except Exception:
        created_at_uk = landlord["created_at"]

    role_raw = (profile["role"] if profile and "role" in profile.keys() else "owner") or "owner"
    role_label = "Owner" if role_raw == "owner" else "Agent"

    return render_template(
        "dashboard.html",
        landlord=landlord,
        profile=profile,
        houses=houses,
        created_at_uk=created_at_uk,
        role_label=role_label
    )
