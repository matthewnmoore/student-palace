# auth.py
from __future__ import annotations

from flask import Blueprint, render_template

# Keep the blueprint name 'auth' so url_for('auth.landlords_entry') works
auth_bp = Blueprint("auth", __name__)

# Landlords entry page used by the "Landlords" button in your navbar.
# Template: templates/landlords_entry.html
@auth_bp.route("/landlords", endpoint="landlords_entry")
def landlords_entry():
    return render_template("landlords_entry.html")
