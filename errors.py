from flask import Blueprint, render_template
from models import list_cities

errors_bp = Blueprint("errors", __name__)

@errors_bp.app_errorhandler(404)
def not_found(e):
    cities = list_cities()
    # Show the search page with a friendly message
    return render_template("search.html", query={"error": "Page not found"}, cities=cities), 404

@errors_bp.app_errorhandler(500)
def server_error(e):
    cities = list_cities()
    return render_template("search.html", query={"error": "Something went wrong"}, cities=cities), 500
