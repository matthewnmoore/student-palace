# admin/backup.py
from __future__ import annotations
import io, os, time, json, zipfile
from pathlib import Path
from flask import render_template, request, redirect, url_for, flash, send_file, abort
from . import bp, require_admin
from backup_to_dropbox import run_backup

def _add_dir_to_zip(zf, base: Path, arc_prefix: str):
    total_files, total_bytes = 0, 0
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

def _build_backup_zip():
    try:
        from db import DB_PATH
    except Exception:
        return None, None

    project_root = Path(__file__).resolve().parents[1]
    uploads_dir = project_root / "static" / "uploads"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())

        db_info = {"exists": False, "bytes": 0, "path": DB_PATH}
        try:
            db_path = Path(DB_PATH)
            if db_path.exists():
                zf.write(db_path, arcname="database/student_palace.db")
                db_info["exists"] = True
                db_info["bytes"] = int(db_path.stat().st_size)
        except Exception:
            pass

        uploads_info = _add_dir_to_zip(zf, uploads_dir, "site-files/static/uploads")

        manifest = {
            "created_at": ts,
            "database": db_info,
            "uploads": uploads_info,
            "paths": {"db_path": DB_PATH, "uploads_dir": str(uploads_dir)},
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    buf.seek(0)
    filename = f"student-palace-backup-{time.strftime('%Y%m%d-%H%M%SZ', time.gmtime())}.zip"
    return buf, filename

@bp.route("/backup", methods=["GET", "POST"])
def admin_backup():
    # Require admin
    r = require_admin()
    if r:
        return r

    # Handle Dropbox upload (form POST)
    if request.method == "POST":
        try:
            dropbox_path = run_backup()
            flash(f"✅ Backup uploaded to Dropbox: {dropbox_path}", "success")
        except Exception as e:
            flash(f"❌ Backup failed: {e}", "danger")
        return redirect(url_for("admin.admin_backup"))

    # Handle ZIP download (?download=1)
    if request.args.get("download"):
        buf, filename = _build_backup_zip()
        if not buf:
            return abort(500, "Backup failed")
        return send_file(
            buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
        )

    # Default: render backup page with buttons
    return render_template("admin/backup.html")
