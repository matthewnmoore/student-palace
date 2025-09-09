# admin/backup.py
from __future__ import annotations

import io, os, time, json, zipfile
from pathlib import Path
from flask import request, abort, jsonify, send_file
from . import bp, require_admin

# Safe import: don't explode if Dropbox isn't configured in this env
try:
    from backup_to_dropbox import run_backup
except Exception:
    run_backup = None

# ---------- 1) INSTANT DOWNLOAD (same endpoint name your template uses) ----------
@bp.get("/backup", endpoint="admin_backup")
def admin_backup_download():
    # Require admin session for manual download
    maybe_redirect = require_admin()
    if maybe_redirect:
        return maybe_redirect

    # Build the ZIP fully in memory
    try:
        from db import DB_PATH
    except Exception:
        abort(500, "DB not available")

    project_root = Path(__file__).resolve().parents[1]
    uploads_dir = project_root / "static" / "uploads"

    def _add_dir_to_zip(zf: zipfile.ZipFile, base: Path, arc_prefix: str) -> dict:
        import os
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

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())

        # 1) Database file
        db_info = {"exists": False, "bytes": 0, "path": DB_PATH}
        try:
            db_path = Path(DB_PATH)
            if db_path.exists():
                zf.write(db_path, arcname="database/student_palace.db")
                db_info["exists"] = True
                db_info["bytes"] = int(db_path.stat().st_size)
        except Exception:
            pass

        # 2) Uploads (images)
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

# ---------- 2) CRON (GET with token; no login required) ----------
@bp.get("/backup/cron", endpoint="admin_backup_cron")
def admin_backup_cron():
    token = request.args.get("token", "")
    expected = os.getenv("BACKUP_CRON_TOKEN", "")
    if not expected or token != expected:
        abort(403)  # bad/missing token

    if run_backup is None:
        abort(500, "Dropbox backup not configured")

    dropbox_path = run_backup()
    return jsonify({"status": "ok", "dropbox_path": dropbox_path})
