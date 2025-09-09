# admin/backup.py
from __future__ import annotations

import io, os, time, json, zipfile
from pathlib import Path
from flask import current_app, send_file, abort, request
from . import bp, require_admin

# If you already have this module from earlier work, keep it.
# It should expose run_backup() that builds a backup and uploads to Dropbox.
try:
    from backup_to_dropbox import run_backup  # noqa: F401
except Exception:  # don't crash if not configured yet
    run_backup = None


def _add_dir_to_zip(zf: zipfile.ZipFile, base: Path, arc_prefix: str) -> dict:
    total_files = 0
    total_bytes = 0
    if not base.exists():
        return {"files": 0, "bytes": 0}

    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            if name.endswith((".pyc", ".pyo", ".DS_Store")):
                continue
            abs_path = Path(root) / name
            try:
                rel = abs_path.relative_to(base)
            except Exception:
                rel = Path(name)
            arcname = str(Path(arc_prefix) / rel)
            try:
                zf.write(abs_path, arcname)
                st = abs_path.stat()
                total_files += 1
                total_bytes += int(st.st_size)
            except Exception:
                pass
    return {"files": total_files, "bytes": total_bytes}


@bp.route("/backup", methods=["GET"])
def admin_backup():
    """
    INSTANT DOWNLOAD: returns a ZIP with DB + uploads (no intermediate page).
    """
    # admin gate
    maybe_redirect = require_admin()
    if maybe_redirect:
        return maybe_redirect

    # lazy import to avoid circulars
    try:
        from db import DB_PATH
    except Exception:
        return abort(500, "DB not available")

    project_root = Path(__file__).resolve().parents[1]
    uploads_dir = project_root / "static" / "uploads"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())

        # 1) Database file
        db_info = {"exists": False, "bytes": 0, "path": DB_PATH}
        try:
            db_path = Path(DB_PATH)
            if db_path.exists():
                # put db at a stable name inside the zip
                zf.write(db_path, arcname="database/student_palace.db")
                db_info["exists"] = True
                db_info["bytes"] = int(db_path.stat().st_size)
        except Exception:
            pass  # best-effort

        # 2) Uploads directory
        uploads_info = _add_dir_to_zip(zf, uploads_dir, "site-files/static/uploads")

        # 3) Manifest
        manifest = {
            "created_at": ts,
            "notes": "Student Palace manual backup (in-memory).",
            "database": db_info,
            "uploads": uploads_info,
            "paths": {
                "db_path": DB_PATH,
                "uploads_dir": str(uploads_dir),
            },
            "versions": {"python_time": time.time()},
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

    buf.seek(0)
    filename = f"student-palace-backup-{time.strftime('%Y%m%d-%H%M%SZ', time.gmtime())}.zip"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
        max_age=0,
        etag=False,
        conditional=False,
        last_modified=None,
    )


@bp.route("/backup/cron", methods=["POST"])
def admin_backup_cron():
    """
    CRON endpoint for scheduled Dropbox backup.
    Protect with a token so you can call it from your scheduler.
    """
    token = request.args.get("token") or request.headers.get("X-Backup-Token")
    expected = current_app.config.get("BACKUP_CRON_TOKEN")
    if not expected or token != expected:
        return abort(403, "Forbidden")

    if run_backup is None:
        return abort(500, "Dropbox backup not configured")

    try:
        dropbox_path = run_backup()
        return {"status": "ok", "dropbox_path": dropbox_path}
    except Exception as e:
        current_app.logger.exception("Scheduled backup failed")
        return abort(500, f"Backup failed: {e}")
