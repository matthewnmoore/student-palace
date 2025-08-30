# admin/backups.py
from __future__ import annotations

import os
import io
import time
import zipfile
from pathlib import Path
from flask import request, abort, send_file, current_app, flash, redirect, url_for

from . import bp  # admin blueprint
from db import DB_PATH


def _iter_files(root: Path):
    """Yield all files under root (depth-first)."""
    for p in root.rglob("*"):
        if p.is_file():
            yield p


@bp.route("/admin/backup", methods=["GET"])
def admin_backup_download():
    """
    Creates a ZIP containing:
      - The SQLite DB file
      - All house images (static/uploads/houses)
    and streams it back as a download.

    Security:
      - If BACKUP_TOKEN is set in env, require ?token=<value> to proceed.
      - Otherwise, route is open to any logged-in admin (assumes admin auth elsewhere).
    """
    # Optional token check (recommended)
    env_token = os.environ.get("BACKUP_TOKEN")
    if env_token:
        supplied = request.args.get("token", "")
        if supplied != env_token:
            # Don’t leak that a token exists
            abort(403)

    # Resolve important paths
    proj_root = Path(__file__).resolve().parents[1]           # project root (…/src)
    db_file = Path(DB_PATH).resolve()
    houses_dir = (proj_root / "static" / "uploads" / "houses").resolve()

    # Make a /uploads/backups folder (this is durable on Render if you mounted it there)
    backups_dir = (proj_root / "uploads" / "backups")
    backups_dir.mkdir(parents=True, exist_ok=True)

    # Timestamped filename
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    zip_name = f"site-backup-{ts}.zip"
    zip_path = backups_dir / zip_name

    # Build the zip
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1) DB file
        if db_file.exists():
            # Store DB under a stable path inside the zip
            zf.write(db_file, arcname="database/student_palace.sqlite")

        # 2) House images
        if houses_dir.exists():
            prefix_len = len(str(houses_dir.parent)) + 1  # place under media/houses/…
            for f in _iter_files(houses_dir):
                rel = str(f)[prefix_len:]  # e.g. "houses/house1_....jpg"
                zf.write(f, arcname=f"media/{rel}")

        # 3) Tiny manifest
        manifest = (
            "{\n"
            f'  "created_at_utc": "{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}",\n'
            f'  "db_path": "{db_file}",\n'
            f'  "images_root": "{houses_dir}"\n'
            "}\n"
        )
        zf.writestr("manifest.json", manifest)

    # Keep only the last N zips (e.g., 20)
    try:
        zips = sorted(backups_dir.glob("site-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in zips[20:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass

    # Stream the file to the browser
    return send_file(
        zip_path,
        as_attachment=True,
        download_name=zip_name,
        mimetype="application/zip",
        max_age=0,
        conditional=True,
    )
