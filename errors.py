# errors.py
from flask import render_template

def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        # Import inside the handler to avoid circular imports
        try:
            from models import get_active_cities_safe
            cities = get_active_cities_safe()
        except Exception:
            cities = []
        return render_template(
            "search.html",
            query={"error": "Page not found"},
            cities=cities
        ), 404

    @app.errorhandler(500)
    def server_error(e):
        # Keep this generic to avoid referencing settings that may not exist here
        print("[ERROR] 500:", e)
        try:
            from models import get_active_cities_safe
            cities = get_active_cities_safe()
        except Exception:
            cities = []
        return render_template(
            "search.html",
            query={"error": "Something went wrong"},
            cities=cities
        ), 500
