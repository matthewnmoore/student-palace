# landlord/accreditations.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils import require_landlord, current_landlord_id
from . import bp


@bp.route("/landlord/accreditations", methods=["GET", "POST"])
def landlord_accreditations():
    """
    Let a landlord choose accreditations (checkbox + optional notes).

    Data model:
      - Admin manages accreditation_types (id, name, help_text, sort_order, is_active).
      - Landlord selections live in landlord_accreditations (landlord_id, scheme_id, extra_text).
        NOTE: 'scheme_id' points to accreditation_types.id (historic column name retained).
    """
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()

    conn = get_db()
    try:
        # Landlord profile (for verified banner)
        profile = conn.execute(
            "SELECT * FROM landlord_profiles WHERE landlord_id = ?", (lid,)
        ).fetchone()

        # Current selections for this landlord
        rows = conn.execute(
            """
            SELECT scheme_id, COALESCE(extra_text,'') AS extra_text
            FROM landlord_accreditations
            WHERE landlord_id = ?
            """,
            (lid,),
        ).fetchall()
        current = {row["scheme_id"]: row["extra_text"] for row in rows}
        current_ids = set(current.keys())

        # Active accreditations (admin-managed)
        active = conn.execute(
            """
            SELECT id, name, COALESCE(help_text,'') AS help_text,
                   COALESCE(sort_order, 0) AS sort_order,
                   COALESCE(is_active, 1) AS is_active
            FROM accreditation_types
            WHERE is_active = 1
            ORDER BY sort_order ASC, name ASC
            """
        ).fetchall()
        active_ids = {r["id"] for r in active}

        # Inactive but previously selected (so the landlord can unselect if desired)
        missing_ids = list(current_ids - active_ids)
        inactive_selected = []
        if missing_ids:
            placeholders = ",".join("?" for _ in missing_ids)
            inactive_selected = conn.execute(
                f"""
                SELECT id, name, COALESCE(help_text,'') AS help_text,
                       COALESCE(sort_order, 0) AS sort_order,
                       COALESCE(is_active, 0) AS is_active
                FROM accreditation_types
                WHERE id IN ({placeholders})
                ORDER BY name ASC
                """,
                tuple(missing_ids),
            ).fetchall()

        # Final list shown to the landlord
        # Keep actives first (admin order), then any inactive-but-selected.
        schemes = list(active) + list(inactive_selected)

        if request.method == "POST":
            # Build a set of checked scheme IDs from form (covering both active and inactive-visible)
            checked_ids = set()
            for s in schemes:
                key = f"scheme_{s['id']}"
                if request.form.get(key) in ("1", "on", "true"):
                    checked_ids.add(s["id"])

            # Upsert checked ones (with notes), delete unchecked ones
            for s in schemes:
                sid = s["id"]
                notes = (request.form.get(f"extra_{sid}") or "").strip()

                if sid in checked_ids:
                    if sid in current:
                        conn.execute(
                            """
                            UPDATE landlord_accreditations
                               SET extra_text = ?
                             WHERE landlord_id = ? AND scheme_id = ?
                            """,
                            (notes, lid, sid),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT INTO landlord_accreditations (landlord_id, scheme_id, extra_text)
                            VALUES (?, ?, ?)
                            """,
                            (lid, sid, notes),
                        )
                else:
                    if sid in current:
                        conn.execute(
                            "DELETE FROM landlord_accreditations WHERE landlord_id = ? AND scheme_id = ?",
                            (lid, sid),
                        )

            conn.commit()
            flash("Accreditations updated.", "ok")
            return redirect(url_for("landlord.landlord_accreditations"))

        # GET render
        return render_template(
            "landlord_accreditations.html",
            profile=profile,
            schemes=schemes,
            current=current,
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass
