# admin/auth.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, session, flash, current_app
from . import bp, _admin_token, _is_admin

@bp.route("/")
def admin_index():
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))
    # Simple landing page with links to sections
    return render_template("admin_index.html")

@bp.route("/login", methods=["GET", "POST"])
def admin_login():
    try:
        if request.method == "POST":
            token = (request.form.get("token") or "").strip()
            if _admin_token() and token == _admin_token():
                session["is_admin"] = True
                flash("Admin session started.", "ok")
                return redirect(url_for("admin.admin_index"))
            flash("Invalid admin token.", "error")
        return render_template("admin_login.html")
    except Exception as e:
        current_app.logger.error("admin_login: %s", e)
        flash("Admin login error.", "error")
        return redirect(url_for("public.index"))

@bp.route("/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.", "ok")
    return redirect(url_for("public.index"))
