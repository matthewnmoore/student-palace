# app.py
from flask import Flask
import datetime

from config import SECRET_KEY
from db import ensure_db
from public import public_bp
from auth import auth_bp
from admin import bp as admin_bp          # fixed: import the shared admin blueprint as admin_bp
from landlord import bp as landlord_bp    # landlord blueprint
from errors import register_error_handlers


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY

    # Ensure DB is created / migrated once at boot
    ensure_db()

    # Version string (cache busting + footer badge)
    build_version = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    @app.context_processor
    def inject_globals():
        import datetime as _dt
        return {
            "BUILD_VERSION": build_version,
            "now": _dt.datetime.utcnow,
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
