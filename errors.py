from flask import Blueprint, jsonify, request

errors_bp = Blueprint("errors", __name__)

@errors_bp.app_errorhandler(404)
def not_found(e):
    # For JSON-ish requests, return JSON
    path = request.path or ""
    if path.endswith(".json") or "application/json" in (request.headers.get("Accept") or ""):
        return jsonify({"error": "not found", "path": path}), 404
    # Keep it dead-simple to avoid secondary template errors
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>Not found</title>"
        "<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:32px;background:#f9f7ff;color:#333}</style>"
        "<h1>Page not found</h1>"
        "<p>Sorry, we couldn’t find that page.</p>",
        404,
        {"Content-Type": "text/html; charset=utf-8"},
    )

@errors_bp.app_errorhandler(500)
def server_error(e):
    path = request.path or ""
    if path.endswith(".json") or "application/json" in (request.headers.get("Accept") or ""):
        return jsonify({"error": "server error"}), 500
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>Something went wrong</title>"
        "<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:32px;background:#f9f7ff;color:#333}</style>"
        "<h1>Something went wrong</h1>"
        "<p>We’re working on it. Try again in a moment.</p>",
        500,
        {"Content-Type": "text/html; charset=utf-8"},
    )
