from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from db import get_db
from . import bp, require_admin

# The 5 flags we expose in the UI
SETTING_KEYS = [
    "show_metric_landlords",
    "show_metric_houses",
    "show_metric_rooms",
    "show_metric_students",
    "show_metric_photos",
]

# Text settings managed on this page
TEXT_KEYS = [
    "terms_md",  # Markdown/HTML for Terms & Conditions shown to users
]

DEFAULTS = {
    "show_metric_landlords": "1",
    "show_metric_houses": "1",
    "show_metric_rooms": "1",
    "show_metric_students": "0",
    "show_metric_photos": "0",
    "terms_md": "",  # empty by default; admin can fill in
}

def _get_settings(conn) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM site_settings").fetchall()
    got = {r["key"]: r["value"] for r in rows}
    # ensure defaults for missing keys (do not write yet)
    for k, v in DEFAULTS.items():
        got.setdefault(k, v)
    return got

@bp.route("/settings", methods=["GET", "POST"], endpoint="admin_settings")
def admin_settings():
    r = require_admin()
    if r:
        return r

    conn = get_db()
    try:
        if request.method == "POST":
            # Save each checkbox as "1" or "0"
            for k in SETTING_KEYS:
                val = "1" if request.form.get(k) == "on" else "0"
                conn.execute(
                    "INSERT OR REPLACE INTO site_settings(key, value) VALUES (?, ?)",
                    (k, val),
                )

            # Save text fields exactly as provided (no trimming here to allow leading/trailing markdown)
            for k in TEXT_KEYS:
                val = request.form.get(k, "")
                conn.execute(
                    "INSERT OR REPLACE INTO site_settings(key, value) VALUES (?, ?)",
                    (k, val),
                )

            conn.commit()
            flash("Site settings saved.", "ok")
            return redirect(url_for("admin.admin_settings"))

        # GET
        settings = _get_settings(conn)
        return render_template("admin_settings.html", settings=settings)
    finally:
        conn.close()
