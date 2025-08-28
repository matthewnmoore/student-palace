from flask import Flask
import datetime

from config import SECRET_KEY
from db import ensure_db
from public import public_bp
from auth import auth_bp
from admin import admin_bp
# NEW: import the shared blueprint from the landlord package
from landlord import bp as landlord_bp
from errors import register_error_handlers


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY

    # Called once at boot (safe if DB already exists/migrated)
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

    # Blueprints
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(landlord_bp)  # from landlord package

    # Error handlers
    register_error_handlers(app)

    return app


# Gunicorn entrypoint
app = create_app()

if __name__ == "__main__":
    # Local dev
    app.run(host="0.0.0.0", port=5000, debug=True)
