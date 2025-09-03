# app.py
from __future__ import annotations

import datetime
from flask import Flask, jsonify, request, abort

from config import SECRET_KEY
from db import ensure_db, DB_PATH
from public import public_bp
from auth import auth_bp
from admin import bp as admin_bp          # shared admin blueprint
from landlord import bp as landlord_bp    # landlord blueprint
from errors import register_error_handlers

# --- Robust import for the public property page blueprint ---
# We can't "from public.property_public import ..." because public.py at repo root
# shadows the 'public' package. So we load the file directly and fetch its blueprint.
try:
    # Try the direct package-style import first (works if you ever make 'public' a package)
    from public.property_public import property_public_bp  # type: ignore
except Exception:
    import importlib.util
    from pathlib import Path

    _pp_path = Path(__file__).parent / "public" / "property_public.py"
    _spec = importlib.util.spec_from_file_location("property_public", str(_pp_path))
    if _spec is None or _spec.loader is None:
        raise ImportError(f"Could not load property_public.py from {_pp_path}")
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)  # type: ignore[attr-defined]
    # Support either export name
    property_public_bp = getattr(_mod, "property_public_bp", getattr(_mod, "bp"))


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY

    # Ensure DB is created / migrated once at boot (non-destructive)
    ensure_db()

    # Version string (cache busting + footer badge)
    build_version = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    @app.context_processor
    def inject_globals():
        import datetime as _dt
        return {"BUILD_VERSION": build_version, "now": _dt.datetime.utcnow}

    # Register blueprints
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(landlord_bp)
    app.register_blueprint(property_public_bp)   # register the public property blueprint

    # Register error handlers
    register_error_handlers(app)

    # -------------------------
    # DEBUG / ADMIN UTILITIES
    # -------------------------

    @app.route("/debug/db")
    def debug_db():
        import os, time
        from db import get_db

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

        # Path SQLite reports (should match DB_PATH)
        sqlite_db_file = None
        try:
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
        import time
        from pathlib import Path

        base = Path("/opt/render/project/src")
        candidates = []
        for p in base.rglob("*.db"):
            try:
                st = p.stat()
                candidates.append({
                    "path": str(p),
                    "size_bytes": st.st_size,
                    "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
                })
            except Exception as e:
                candidates.append({"path": str(p), "error": str(e)})

        candidates.sort(key=lambda r: r.get("size_bytes", 0), reverse=True)
        return {"db_candidates": candidates}

    @app.route("/debug/db-scan")
    def debug_db_scan():
        import sqlite3, time
        from pathlib import Path

        base = Path("/opt/render/project/src")
        results = []
        for p in base.rglob("*.db"):
            info = {"path": str(p)}
            try:
                st = p.stat()
                info.update({
                    "size_bytes": st.st_size,
                    "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
                })
            except Exception as e:
                info["stat_error"] = str(e)

            # Try opening and counting rows
            try:
                conn = sqlite3.connect(str(p))
                conn.row_factory = sqlite3.Row
                counts = {}
                for t in ["landlords", "landlord_profiles", "cities", "houses", "rooms", "house_images"]:
                    try:
                        counts[t] = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
                    except Exception:
                        counts[t] = "n/a"
                info["counts"] = counts

                sample = []
                try:
                    rows = conn.execute(
                        "SELECT id, title, city, created_at FROM houses ORDER BY id DESC LIMIT 3"
                    ).fetchall()
                    sample = [dict(r) for r in rows]
                except Exception:
                    pass
                info["houses_sample"] = sample

                conn.close()
            except Exception as e:
                info["open_error"] = str(e)

            results.append(info)

        results.sort(key=lambda r: r.get("size_bytes", 0), reverse=True)
        return {"db_scan": results}

    # --- Protected on-disk backup (keeps last 20). Call before risky changes.
    @app.route("/debug/db-backup", methods=["POST"])
    def debug_db_backup():
        import os, time, shutil
        from pathlib import Path

        admin_token = os.environ.get("ADMIN_TOKEN", "")
        token = request.args.get("token", "")
        if not admin_token or token != admin_token:
            return abort(403)

        src = Path(DB_PATH)
        if not src.exists():
            return jsonify({"ok": False, "error": "DB not found", "path": str(src)}), 404

        backups_dir = src.parent / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)

        ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        dest = backups_dir / f"student_palace.{ts}.sqlite"
        shutil.copy2(src, dest)

        # prune to last 20
        existing = sorted(backups_dir.glob("student_palace.*.sqlite"))
        for p in existing[:-20]:
            try:
                p.unlink()
            except Exception:
                pass

        return jsonify({"ok": True, "created": str(dest), "kept": len(existing[-20:])})

    return app

# Gunicorn entrypoint
app = create_app()

if __name__ == "__main__":
    # Local development only
    app.run(host="0.0.0.0", port=5000, debug=True)
