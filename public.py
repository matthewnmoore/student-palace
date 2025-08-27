from flask import Blueprint, render_template, request
from datetime import datetime as dt

from models import get_db

bp = Blueprint("public", __name__)

# ---------------------------
# Helpers
# ---------------------------

def _get_active_cities_list():
    """Return active city names in admin-defined order."""
    conn = get_db()
    rows = conn.execute(
        "SELECT name FROM cities WHERE is_active=1 ORDER BY sort_order ASC, name ASC"
    ).fetchall()
    conn.close()
    return [r["name"] for r in rows]

def _get_active_cities_rows():
    """Return active city rows with image_url for the home page grid."""
    conn = get_db()
    rows = conn.execute("""
        SELECT name, image_url
        FROM cities
        WHERE is_active=1
        ORDER BY sort_order ASC, name ASC
    """).fetchall()
    conn.close()
    return rows

# ---------------------------
# Routes
# ---------------------------

@bp.route("/")
def index():
    # City list for selects
    cities = _get_active_cities_list()

    # Simple featured placeholder (can be wired later)
    featured = {
        "title": "Spacious 5-bed student house",
        "city": cities[0] if cities else "Leeds",
        "price_pppw": 135,
        "badges": ["Bills included", "Close to campus", "Wi-Fi"],
        "image": "",
        "link": "#",
    }

    # City cards (with image overlays)
    cities_with_meta = _get_active_cities_rows()

    return render_template(
        "index.html",
        cities=cities,
        featured=featured,
        cities_with_meta=cities_with_meta,
    )

@bp.route("/search")
def search():
    cities = _get_active_cities_list()
    q = {
        "city": request.args.get("city", ""),
        "group_size": request.args.get("group_size", ""),
        "gender": request.args.get("gender", ""),
        "ensuite": "on" if request.args.get("ensuite") else "",
        "bills_included": "on" if request.args.get("bills_included") else "",
        "error": "",
    }
    # (Results come later when DB search is wired.)
    return render_template("search.html", query=q, cities=cities)
