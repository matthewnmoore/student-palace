from flask import render_template, jsonify, request
from utils import get_active_cities_safe
from config import ADMIN_DEBUG

def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        path = request.path or ""
        if path.endswith(".json"):
            return jsonify({"error": "not found", "path": path}), 404
        cities = get_active_cities_safe()
        return render_template("search.html", query={"error": "Page not found"}, cities=cities), 404

    @app.errorhandler(500)
    def server_error(e):
        print("[ERROR] 500:", e)
        path = request.path or ""
        if path.endswith(".json"):
            return jsonify({"error": "server error", "detail": str(e)}), 500
        if ADMIN_DEBUG:
            return f"Internal Server Error: {e}", 500
        cities = get_active_cities_safe()
        return render_template("search.html", query={"error": "Something went wrong"}, cities=cities), 500
