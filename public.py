# public.py
from flask import Blueprint, render_template, request
from datetime import datetime as dt

# Import helpers from your models module
from models import get_active_city_names

# --- Blueprint ---
public_bp = Blueprint("public", __name__)

# --- Routes ---

@public_bp.route("/")
def index():
    """
    Home page: shows hero, search form, and featured card.
    Expects a list of city names for the selects and copy blocks.
    """
    cities = get_active_city_names(order_by_admin=True)

    # Simple featured stub (can be wired to DB later)
    featured = {
        "title": "Spacious 5-bed student house",
        "city": cities[0] if cities else "Leeds",
        "price_pppw": 135,
        "badges": ["Bills included", "Close to campus", "Wi-Fi"],
        "image": "",
        "link": "#",
        "generated_at": dt.utcnow().isoformat()
    }

    return render_template("index.html", cities=cities, featured=featured)


@public_bp.route("/search")
def search():
    """
    Basic search echo (DB wiring comes later).
    Keeps params compatible with current templates.
    """
    cities = get_active_city_names(order_by_admin=True)

    q = {
        "city": request.args.get("city", ""),
        "group_size": request.args.get("group_size", ""),
        "gender": request.args.get("gender", ""),
        "ensuite": "on" if request.args.get("ensuite") else "",
        "bills_included": "on" if request.args.get("bills_included") else "",
        "error": None
    }

    return render_template("search.html", query=q, cities=cities)
