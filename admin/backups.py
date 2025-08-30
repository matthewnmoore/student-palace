# admin/backups.py
from __future__ import annotations

import io, os, time, json, zipfile
from pathlib import Path
from flask import send_file, abort
from . import bp, require_admin

# What to include in the backup:
# - The active SQLite DB file (db.DB_PATH)
# - The uploads folder with images: static/uploads/...
# - A small manifest.json with meta info
#
# We do NOT persist any temporary files: the ZIP is built in-memory and streamed.

def _add_dir_to_zip(zf: zipfile.ZipFile, base: Path, arc_prefix: str) -> dict:
    """
    Recursively add a directory to the zip.
    Returns a dict with simple counts: {"files": n, "bytes": total}
    """
    total_files = 0
    total_bytes = 0
    if not base.exists():
        return {"files": 0, "bytes": 0}

    for root, dirs, files in os.walk(base):
        # Skip common noise
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            if name.endswith((".pyc", ".pyo", ".DS_Store")):
                continue
            abs_path = Path(root) / name
            try:
                rel = abs_path.relative_to(base)
            except Exception:
                # Fallback: plain name
                rel = Path(name)
            arcname = str(Path(arc_prefix) / rel)

            try:
                zf.write(abs_path, arcname)
                st = abs_path.stat()
                total_files += 1
                total_bytes += int(st.st_size)
            except Exception:
                # best-effort; skip unreadable files
                pass

    return {"files": total_files, "bytes": total_bytes}


@bp.route("/backup", methods=["GET"])
def admin_backup():
    # Admin gate
    r = require_admin()
    if r:
        return r

    # Lazy imports to avoid circulars
    try:
        from db import DB_PATH
    except Exception:
        return abort(500, "DB not available")

    project_root = Path(__file__).resolve().parents[1]  # /opt/render/project/src
    uploads_dir = project_root / "static" / "uploads"

    # Build the ZIP fully in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())

        # 1) Database file
        db_info = {"exists": False, "bytes": 0, "path": DB_PATH}
        try:
            db_path = Path(DB_PATH)
            if db_path.exists():
                zf.write(db_path, arcname=f"database/student_palace.db")
                db_info["exists"] = True
                db_info["bytes"] = int(db_path.stat().st_size)
        except Exception:
            # If we can't read it, still produce a ZIP with manifest explaining the issue
            pass

        # 2) Uploads (images)
        uploads_info = _add_dir_to_zip(zf, uploads_dir, "site-files/static/uploads")

        # 3) Manifest
        manifest = {
            "created_at": ts,
            "notes": "Student Palace manual backup (in-memory). No temp file saved on server.",
            "database": db_info,
            "uploads": uploads_info,
            "paths": {
                "db_path": DB_PATH,
                "uploads_dir": str(uploads_dir),
            },
            "versions": {
                "python_time": time.time(),
            },
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
