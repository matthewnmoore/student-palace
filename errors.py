# errors.py
# Safe error handlers + explicit register_error_handlers(app)
# - No hard imports at module import time (prevents boot failures)
# - Gracefully falls back if models.list_cities() isn't available

from flask import render_template

def _cities_safe():
    """
    Try to fetch cities from models.list_cities() if present.
    Fall back to an empty list if anything goes wrong.
    """
    try:
        from models import list_cities  # type: ignore
        try:
            return list_cities()
        except Exception:
            return []
    except Exception:
        return []

def not_found(e):
    cities = _cities_safe()
    # Render your existing search placeholder template with a friendly message
    return render_template(
        "search.html",
        query={"error": "Page not found"},
        cities=cities
    ), 404

def server_error(e):
    cities = _cities_safe()
    return render_template(
        "search.html",
        query={"error": "Something went wrong"},
        cities=cities
    ), 500

def register_error_handlers(app):
    """
    Called from app.py to attach handlers without using a Blueprint,
    so it works regardless of blueprint registration order.
    """
    app.register_error_handler(404, not_found)
    app.register_error_handler(500, server_error)
