# admin/tools.py (or add to an existing admin module)
from __future__ import annotations
from flask import redirect, url_for, flash
from datetime import datetime, timezone
from db import get_db
from . import bp, _is_admin

@bp.route("/tools/backfill_photos_created_at", methods=["POST", "GET"])
def admin_backfill_photos_created_at():
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))
    conn = get_db()
    try:
        # Set created_at to NOW for any house_images rows with NULL or empty created_at
        now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        conn.execute("""
            UPDATE house_images
               SET created_at = ?
             WHERE created_at IS NULL
                OR created_at = ''
        """, (now_iso,))
        conn.commit()
        flash("Backfilled created_at for photos.", "ok")
    finally:
        conn.close()
    return redirect(url_for("admin.dashboard"))
