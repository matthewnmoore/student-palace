# admin.py
from __future__ import annotations

import os
from functools import wraps
from typing import Any, Callable, Dict, List

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
)

# --------------------------------------------------------------------------------------
# Optional imports from your project helpers.
# We try to import things if they exist; if not, we fall back safely.
# --------------------------------------------------------------------------------------
try:
    from models import list_cities  # type: ignore
except Exception:  # pragma: no cover
    def list_cities() -> List[str]:  # fallback
        return []

try:
    from models import get_db  # type: ignore  # noqa: F401
except Exception:  # pragma: no cover
    get_db = None  # type: ignore

# If you have a stronger admin verification somewhere else, you can wire it here:
try:
    from utils import verify_admin  # type: ignore
except Exception:  # pragma: no cover
    verify_admin = None  # type: ignore

# --------------------------------------------------------------------------------------
# Blueprint
# --------------------------------------------------------------------------------------
admin_bp = Blueprint("admin", __name__)

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def is_admin_logged_in() -> bool:
    return bool(session.get("is_admin") is True)


def admin_required(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not is_admin_logged_in():
            flash("Please log in to access admin.", "error")
            return redirect(url_for("admin.login"))
        return fn(*args, **kwargs)

    return wrapper


def _check_admin_credentials(email: str, password: str) -> bool:
    """
    Credential check strategy:
      1) If a custom verify_admin helper exists (e.g., checks DB), use it.
      2) Else check against environment variables ADMIN_EMAIL / ADMIN_PASSWORD if set.
      3) Else accept any non-empty email+password (dev fallback) so you can log in
         and test pages. Tighten later if desired.
    """
    if verify_admin:
        try:
            return bool(verify_admin(email, password))
        except Exception:
            # fall through to other checks
            pass

    env_email = os.environ.get("ADMIN_EMAIL")
    env_password = os.environ.get("ADMIN_PASSWORD")
    if env_email or env_password:
        return (email == (env_email or "")) and (password == (env_password or ""))

    # Dev fallback so you aren't locked out while wiring templates/routes.
    return bool(email.strip() and password.strip())


# --------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------
@admin_bp.route("/admin/login", methods=["GET", "POST"], endpoint="login")
def login():
    """
    Admin login page. Keeps the endpoint name 'admin.login' which your templates use.
    Template: templates/admin_login.html
    """
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if _check_admin_credentials(email, password):
            session["is_admin"] = True
            session["admin_email"] = email
            flash("Admin session started.", "success")
            # After successful login, go to the dashboard
            return redirect(url_for("admin.dashboard"))
        else:
            flash("Invalid credentials.", "error")

    return render_template("admin_login.html")


@admin_bp.route("/admin/logout", methods=["POST", "GET"], endpoint="logout")
def logout():
    session.pop("is_admin", None)
    session.pop("admin_email", None)
    flash("Logged out.", "success")
    return redirect(url_for("public.index"))


@admin_bp.route("/admin", endpoint="root")
def admin_root():
    """Covers any redirect to '/admin' by sending users to the real dashboard."""
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/admin/dashboard", endpoint="dashboard")
@admin_required
def dashboard():
    """
    Simple dashboard landing. Template already in your backup:
      templates/dashboard.html
    """
    return render_template("dashboard.html")


# --- Example management pages you already had templates for ----------------------------
# These preserve endpoint names commonly used in earlier code. If your templates link to
# different endpoints, adjust the names/URLs to match.
@admin_bp.route("/admin/cities", methods=["GET"], endpoint="cities")
@admin_required
def cities():
    cities_list = []
    try:
        cities_list = list_cities()
    except Exception:
        cities_list = []
    return render_template("admin_cities.html", cities=cities_list)


@admin_bp.route("/admin/landlords", methods=["GET"], endpoint="landlords")
@admin_required
def landlords():
    # Render your existing template. Pass minimal context; extend as needed later.
    return render_template("admin_landlords.html")


# If you also had routes for CRUD forms (houses, rooms, etc.), keep those in their
# dedicated modules. This file focuses on wiring the admin landing + login paths so
# your navigation and redirects stop falling into the error page.
