# admin/backup.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from . import bp, require_admin  # bp is the shared admin blueprint
from backup_to_dropbox import run_backup

@bp.route("/backup", methods=["GET", "POST"])
def admin_backup():
    # Require admin login
    maybe_redirect = require_admin()
    if maybe_redirect:
        return maybe_redirect

    result = None
    if request.method == "POST":
        try:
            dropbox_path = run_backup()
            flash(f"✅ Backup uploaded to Dropbox: {dropbox_path}", "success")
            result = dropbox_path
        except Exception as e:
            flash(f"❌ Backup failed: {e}", "danger")

    return render_template("admin/backup.html", result=result)
