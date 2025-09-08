# admin/accreditations.py
from __future__ import annotations

import re
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils import require_admin
from . import bp


def slugify(text: str) -> str:
    """Generate a URL-safe slug from the accreditation name."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-") or "item"


@bp.route("/admin/accreditations", methods=["GET", "POST"])
def admin_accreditations():
    """Admin panel for managing accreditation_types."""
    r = require_admin()
    if r:
        return r

    conn = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            name = request.form.get("name", "").strip()
            help_text = request.form.get("help_text", "").strip()
            is_active = 1 if request.form.get("is_active") else 0
            sort_order = int(request.form.get("sort_order") or 0)

            slug = slugify(name)
            # Ensure unique slug
            existing = conn.execute(
                "SELECT 1 FROM accreditation_types WHERE slug = ?", (slug,)
            ).fetchone()
            i = 2
            while existing:
                candidate = f"{slug}-{i}"
                existing = conn.execute(
                    "SELECT 1 FROM accreditation_types WHERE slug = ?", (candidate,)
                ).fetchone()
                if not existing:
                    slug = candidate
                    break
                i += 1

            conn.execute(
                """
                INSERT INTO accreditation_types (name, slug, is_active, sort_order, help_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, slug, is_active, sort_order, help_text),
            )
            conn.commit()
            flash("Accreditation added.", "ok")
            return redirect(url_for("admin.admin_accreditations"))

        if action == "edit":
            aid = int(request.form["id"])
            name = request.form.get("name", "").strip()
            help_text = request.form.get("help_text", "").strip()
            is_active = 1 if request.form.get("is_active") else 0

            conn.execute(
                """
                UPDATE accreditation_types
                   SET name = ?, help_text = ?, is_active = ?
                 WHERE id = ?
                """,
                (name, help_text, is_active, aid),
            )
            conn.commit()
            flash("Accreditation updated.", "ok")
            return redirect(url_for("admin.admin_accreditations"))

        if action == "delete":
            aid = int(request.form["id"])
            conn.execute("DELETE FROM accreditation_types WHERE id = ?", (aid,))
            conn.commit()
            flash("Accreditation deleted.", "ok")
            return redirect(url_for("admin.admin_accreditations"))

        if action == "reorder":
            for key, value in request.form.items():
                if key.startswith("order_"):
                    aid = int(key.split("_")[1])
                    try:
                        sort_order = int(value)
                    except ValueError:
                        sort_order = 0
                    conn.execute(
                        "UPDATE accreditation_types SET sort_order = ? WHERE id = ?",
                        (sort_order, aid),
                    )
            conn.commit()
            flash("Sort order updated.", "ok")
            return redirect(url_for("admin.admin_accreditations"))

    # GET: show current list
    items = conn.execute(
        """
        SELECT id, name, slug, is_active, sort_order, help_text
        FROM accreditation_types
        ORDER BY sort_order ASC, name ASC
        """
    ).fetchall()

    conn.close()
    return render_template("admin_accreditations.html", items=items)
