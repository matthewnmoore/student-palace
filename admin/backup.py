# admin/backup.py
from __future__ import annotations

import io, os, time, json, zipfile
from pathlib import Path
from flask import render_template, request, redirect, url_for, flash, send_file, abort
from . import bp, require_admin
from backup_to_dropbox import run_backup  # keep if you use Dropbox

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

@bp.route("/backup", methods=["GET", "POST"])
def admin_backup():
    maybe_redirect = require_admin()
    if maybe_redirect:
        return maybe_redirect

    if request.method == "POST":
        try:
            dropbox_path = run_backup()
            flash(f"✅ Backup uploaded to Dropbox: {dropbox_path}", "success")
        except Exception as e:
            flash(f"❌ Backup failed: {e}", "danger")

    return render_template("admin/backup.html")

@bp.route("/backup/download", methods=["GET"])
def admin_backup_download():
    maybe_redirect = require_admin()
    if maybe_redirect:
        return maybe_redirect

    try:
        from db import DB_PATH
    except Exception:
        return abort(500, "DB not available")

    project_root = Path(__file__).resolve().parents[1]  # /opt/render/project/src
    uploads_dir = project_root / "static" / "uploads"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1) DB
        db_path = Path(DB_PATH)
        if db_path.exists():
            zf.write(db_path, arcname="database/student_palace.db")
        # 2) uploads
        _add_dir_to_zip(zf, uploads_dir, "site-files/static/uploads")
        # 3) manifest
        manifest = {
            "created_at": time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime()),
            "notes": "Student Palace manual backup (in-memory).",
            "paths": {"db_path": DB_PATH, "uploads_dir": str(uploads_dir)},
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
