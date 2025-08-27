from flask import Blueprint, jsonify, render_template, request
import os
from db import get_db
from utils import get_active_cities_safe

public_bp = Blueprint("public", __name__)

@public_bp.route("/healthz")
def healthz():
    return "ok", 200

@public_bp.route("/diag")
def diag():
    from config import DB_PATH, UPLOAD_FOLDER, SECRET_KEY, ADMIN_DEBUG
    from utils import is_admin, current_landlord_id
    return jsonify({
        "db_path": DB_PATH,
        "upload_folder": UPLOAD_FOLDER,
        "db_exists": os.path.exists(DB_PATH),
        "upload_exists": os.path.isdir(UPLOAD_FOLDER),
        "env_ok": bool(SECRET_KEY),
        "is_admin": bool(is_admin()),
        "landlord_id": current_landlord_id(),
    }), 200

@public_bp.route("/routes")
def routes():
    from flask import current_app as app
    rules = []
    for r in app.url_map.iter_rules():
        rules.append({
            "rule": str(r),
            "endpoint": r.endpoint,
            "methods": sorted(list(r.methods))
        })
    return jsonify(sorted(rules, key=lambda x: x["rule"]))

@public_bp.route("/")
def index():
    cities = get_active_cities_safe()
    featured = {
        "title": "Spacious 5-bed student house",
        "city": cities[0] if cities else "Leeds",
        "price_pppw": 135,
        "badges": ["Bills included", "Close to campus", "Wi-Fi"],
        "image": "",
        "link": "#"
    }
    return render_template("index.html", cities=cities, featured=featured)

@public_bp.route("/search")
def search():
    cities = get_active_cities_safe()
    q = {
        "city": request.args.get("city", ""),
        "group_size": request.args.get("group_size", ""),
        "gender": request.args.get("gender", ""),
        "ensuite": "on" if request.args.get("ensuite") else "",
        "bills_included": "on" if request.args.get("bills_included") else "",
    }
    return render_template("search.html", query=q, cities=cities)

@public_bp.route("/p/<int:hid>")
def property_public(hid):
    conn = get_db()
    h = conn.execute("SELECT * FROM houses WHERE id=?", (hid,)).fetchone()
    conn.close()
    if not h:
        return render_template("property.html", house=None), 404
    return render_template("property.html", house=h)
