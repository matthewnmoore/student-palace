# admin/dashboard.py
from __future__ import annotations

from flask import render_template
from . import bp, require_admin


@bp.route("/")
def admin_index():
    """
    Admin home page: shows links to sections (cities, landlords, images).
    Requires admin login.
    """
    r = require_admin()
    if r:
        return r

    return render_template("admin_index.html")
