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


# --- TEMP: Debug endpoint to inspect house_images schema ---
# Remove this after we verify the DB.
from db import get_db

@public_bp.route("/debug/hi-schema")
def debug_hi_schema():
    conn = get_db()
    try:
        conn.row_factory = __import__("sqlite3").Row

        def table_exists(name: str) -> bool:
            return bool(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone())

        def table_info(name: str):
            try:
                rows = conn.execute(f"PRAGMA table_info({name})").fetchall()
                return [{
                    "cid": r["cid"],
                    "name": r["name"],
                    "type": r["type"],
                    "notnull": r["notnull"],
                    "dflt_value": r["dflt_value"],
                } for r in rows]
            except Exception as e:
                return {"error": str(e)}

        meta_val = None
        if table_exists("schema_meta"):
            row = conn.execute(
                "SELECT val FROM schema_meta WHERE key='house_images_version'"
            ).fetchone()
            meta_val = row["val"] if row else None

        out = {
            "schema_meta_exists": table_exists("schema_meta"),
            "house_images_exists": table_exists("house_images"),
            "house_images_version": meta_val,
            "house_images_columns": table_info("house_images"),
        }
        return out, 200, {"Content-Type": "application/json"}
    finally:
        conn.close()
