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











# --- DEBUG: quick DB inspection route ---
# Paste this into app.py after you create `app = Flask(__name__)`.
# Remove later if you like.
from flask import jsonify

@app.route("/debug/db")
def debug_db():
    import os, time
    from db import DB_PATH, get_db

    conn = get_db()

    # Which SQLite file are we actually using?
    pragma_list = []
    try:
        pragma_list = conn.execute("PRAGMA database_list").fetchall()
    except Exception:
        pass

    # Table counts (best-effort)
    tables = ["landlords", "houses", "rooms", "house_images", "cities", "landlord_profiles"]
    counts = {}
    for t in tables:
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
        except Exception:
            counts[t] = "n/a"

    # Small sample to prove what's inside
    latest_houses = []
    try:
        rows = conn.execute(
            "SELECT id, title, city, created_at FROM houses ORDER BY id DESC LIMIT 5"
        ).fetchall()
        latest_houses = [dict(r) for r in rows]
    except Exception:
        latest_houses = []

    # File stats
    stat = {}
    try:
        st = os.stat(DB_PATH)
        stat = {
            "size_bytes": st.st_size,
            "mtime_unix": st.st_mtime,
            "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
        }
    except Exception:
        stat = {"error": "could not stat DB_PATH"}

    # Also show the path SQLite reports (should match DB_PATH)
    sqlite_db_file = None
    try:
        # PRAGMA database_list rows: (seq, name, file)
        sqlite_db_file = pragma_list[0][2] if pragma_list else None
    except Exception:
        pass

    conn.close()
    return jsonify({
        "db_path_env": DB_PATH,
        "db_path_sqlite": sqlite_db_file,
        "file_stat": stat,
        "table_counts": counts,
        "latest_houses_sample": latest_houses,
    })





@app.route("/debug/db-candidates")
def debug_db_candidates():
    import os
    from pathlib import Path
    base = Path(__file__).resolve().parent
    candidates = [
        base / "student_palace.db",
        base / "uploads" / "student_palace.db",
    ]
    out = []
    for p in candidates:
        try:
            st = os.stat(p)
            out.append({"path": str(p), "exists": True, "size_bytes": st.st_size})
        except FileNotFoundError:
            out.append({"path": str(p), "exists": False, "size_bytes": 0})
    return {"candidates": out}
