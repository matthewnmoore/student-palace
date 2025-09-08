from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils import require_landlord, current_landlord_id
from . import bp


@bp.route("/landlord/accreditations", methods=["GET", "POST"])
def landlord_accreditations():
    """
    Landlord selects accreditations (checkbox + optional notes).

    Uses:
      - accreditation_types(id, name, help_text, is_active, sort_order)
      - landlord_accreditations(landlord_id, scheme_id, extra_text)
        where scheme_id → accreditation_types.id
    """
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()

    conn = get_db()

    # Landlord profile (for verified banner)
    profile = conn.execute(
        "SELECT * FROM landlord_profiles WHERE landlord_id = ?",
        (lid,),
    ).fetchone()

    # Active accreditations to choose from (admin-managed)
    schemes = conn.execute(
        """
        SELECT id, name, help_text, is_active, sort_order,
               1 AS has_notes
          FROM accreditation_types
         WHERE is_active = 1
         ORDER BY sort_order ASC, name ASC
        """
    ).fetchall()

    # Current selections for this landlord
    rows = conn.execute(
        """
        SELECT scheme_id, COALESCE(extra_text,'') AS extra_text
          FROM landlord_accreditations
         WHERE landlord_id = ?
        """,
        (lid,),
    ).fetchall()
    current = {int(row["scheme_id"]): row["extra_text"] for row in rows}

    if request.method == "POST":
        # Which boxes were checked?
        checked_ids: set[int] = set()
        for s in schemes:
            sid = int(s["id"])
            if request.form.get(f"scheme_{sid}") in ("1", "on", "true"):
                checked_ids.add(sid)

        # Upsert checked ones (with notes); delete unchecked ones
        for s in schemes:
            sid = int(s["id"])
            notes = (request.form.get(f"extra_{sid}") or "").strip()

            if sid in checked_ids:
                if sid in current:
                    # Update existing
                    conn.execute(
                        """
                        UPDATE landlord_accreditations
                           SET extra_text = ?
                         WHERE landlord_id = ? AND scheme_id = ?
                        """,
                        (notes, lid, sid),
                    )
                else:
                    # Insert new
                    conn.execute(
                        """
                        INSERT INTO landlord_accreditations (landlord_id, scheme_id, extra_text)
                        VALUES (?, ?, ?)
                        """,
                        (lid, sid, notes),
                    )
            else:
                # Remove if previously chosen
                if sid in current:
                    conn.execute(
                        """
                        DELETE FROM landlord_accreditations
                         WHERE landlord_id = ? AND scheme_id = ?
                        """,
                        (lid, sid),
                    )

        conn.commit()
        conn.close()
        flash("Accreditations updated.", "ok")
        return redirect(url_for("landlord.landlord_accreditations"))

    # GET render
    selected_ids = set(current.keys())
    conn.close()
    return render_template(
        "landlord_accreditations.html",
        profile=profile,
        schemes=schemes,          # list of accreditation_types
        current=current,          # {scheme_id: extra_text}
        selected_ids=selected_ids # for persistent checkmarks
    )
