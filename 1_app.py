# app.py
from __future__ import annotations

import datetime
from flask import Flask

from config import SECRET_KEY
from db import ensure_db
from public import public_bp                     # public blueprint (has /p/<id>)
from auth import auth_bp
from admin import bp as admin_bp                 # shared admin blueprint
from landlord import bp as landlord_bp           # landlord blueprint
from errors import register_error_handlers


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY

    # Ensure DB is created / migrated once at boot (non-destructive)
    ensure_db()

    # Version string (cache busting + footer badge)
    build_version = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    @app.context_processor
    def inject_globals():
        """Inject BUILD_VERSION, now(), and footer_metrics for the base template."""
        import datetime as _dt
        footer_metrics = []
        try:
            # Lazy import to avoid circulars at import time
            from db import get_db
            conn = get_db()

            # Read feature flags (defaulting to '0' when missing)
            def flag(key: str) -> bool:
                try:
                    row = conn.execute(
                        "SELECT value FROM site_settings WHERE key=?", (key,)
                    ).fetchone()
                    return (row and str(row["value"]) == "1")
                except Exception:
                    return False

            want_landlords = flag("show_metric_landlords")
            want_houses    = flag("show_metric_houses")
            want_rooms     = flag("show_metric_rooms")
            want_students  = flag("show_metric_students")
            want_photos    = flag("show_metric_photos")

            # Helper to count safely
            def count(table: str) -> int:
                try:
                    r = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
                    return int(r["c"] if r else 0)
                except Exception:
                    return 0

            # Build phrases in preferred order
            if want_landlords:
                n = count("landlords")
                footer_metrics.append(f"{n} landlord" if n == 1 else f"{n} landlords")
            if want_houses:
                n = count("houses")
                footer_metrics.append(f"{n} house" if n == 1 else f"{n} houses")
            if want_rooms:
                n = count("rooms")
                footer_metrics.append(f"{n} room" if n == 1 else f"{n} rooms")
            if want_students:
                n = count("students")
                footer_metrics.append(f"{n} student" if n == 1 else f"{n} students")
            # sum both tables (safe even if room_images doesn't exist)
            if want_photos:
                n = count("house_images") + count("room_images")
                footer_metrics.append(f"{n} photo" if n == 1 else f"{n} photos")
            
            try:
                conn.close()
            except Exception:
                pass
        except Exception:
            # On any error, just show nothing in the footer
            footer_metrics = []

        return {
            "BUILD_VERSION": build_version,
            "now": _dt.datetime.utcnow,
            "footer_metrics": footer_metrics,
        }

    # Register blueprints
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(landlord_bp)

    # Register error handlers
    register_error_handlers(app)

    return app


# Gunicorn entrypoint
app = create_app()

if __name__ == "__main__":
    # Local development only
    app.run(host="0.0.0.0", port=5000, debug=True)
