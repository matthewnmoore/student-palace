# app.py
from __future__ import annotations

import datetime
from flask import Flask

from config import SECRET_KEY
from public import public_bp                     # public blueprint (has /p/<id>)
from auth import auth_bp
from admin import bp as admin_bp                 # shared admin blueprint
from landlord import bp as landlord_bp           # landlord blueprint
from errors import register_error_handlers
from room_public import room_public_bp

# NEW: SQLAlchemy session + text for lightweight queries in the context processor
from db import get_db_session
from sqlalchemy import text


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY

    # NOTE: With SQLAlchemy + Alembic we no longer call ensure_db() here.

    # Version string (cache busting + footer badge)
    build_version = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    @app.context_processor
    def inject_globals():
        """Inject BUILD_VERSION, now(), and footer_metrics for the base template."""
        import datetime as _dt
        footer_metrics = []

        # Helper: read a feature flag from site_settings (falls back to False)
        def flag(db, key: str) -> bool:
            try:
                row = db.execute(
                    text("SELECT value FROM site_settings WHERE key = :k"),
                    {"k": key},
                ).first()
                # Treat "1" as True (historical behavior)
                return bool(row and str(row[0]) == "1")
            except Exception:
                # Table may not exist yet; fail closed
                return False

        # Helper: count rows safely from a table name
        def count(db, table: str) -> int:
            try:
                res = db.execute(text(f"SELECT COUNT(*) FROM {table}"))
                return int(res.scalar() or 0)
            except Exception:
                # Table might not exist yet
                return 0

        try:
            with get_db_session() as db:
                want_landlords = flag(db, "show_metric_landlords")
                want_houses    = flag(db, "show_metric_houses")
                want_rooms     = flag(db, "show_metric_rooms")
                want_students  = flag(db, "show_metric_students")
                want_photos    = flag(db, "show_metric_photos")

                if want_landlords:
                    n = count(db, "landlords")
                    footer_metrics.append(f"{n} landlord" if n == 1 else f"{n} landlords")
                if want_houses:
                    n = count(db, "houses")
                    footer_metrics.append(f"{n} house" if n == 1 else f"{n} houses")
                if want_rooms:
                    n = count(db, "rooms")
                    footer_metrics.append(f"{n} room" if n == 1 else f"{n} rooms")
                if want_students:
                    n = count(db, "students")
                    footer_metrics.append(f"{n} student" if n == 1 else f"{n} students")
                if want_photos:
                    # Sum both tables; each count() call is independently guarded
                    n = count(db, "house_images") + count(db, "room_images")
                    footer_metrics.append(f"{n} photo" if n == 1 else f"{n} photos")
        except Exception:
            # On any error, just show nothing in the footer (keep the site up)
            footer_metrics = []

        return {
            "BUILD_VERSION": build_version,
            "now": _dt.datetime.utcnow,
            "footer_metrics": footer_metrics,
        }

    # Register blueprints
    app.register_blueprint(public_bp)
    app.register_blueprint(room_public_bp)
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
