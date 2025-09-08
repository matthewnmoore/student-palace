# landlord/accreditations.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils import require_landlord, current_landlord_id
from . import bp


@bp.route("/landlord/accreditations", methods=["GET", "POST"])
def landlord_accreditations():
    """Let a landlord choose accreditations (checkbox + optional notes)."""
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()

    conn = get_db()

    # Pull landlord profile (for verified banner)
    profile = conn.execute(
        "SELECT * FROM landlord_profiles WHERE landlord_id = ?", (lid,)
    ).fetchone()

    # Active accreditations for landlords to choose from
    accreditations = conn.execute(
        """
        SELECT id,
               name,
               help_text,
               is_active,
               sort_order,
               1 AS has_notes  -- set to 0 if you ever want no notes box
        FROM accreditation_types
        WHERE is_active = 1
        ORDER BY sort_order ASC, name ASC
        """
    ).fetchall()

    # Current selections for this landlord
    rows = conn.execute(
        """
        SELECT accreditation_id, COALESCE(note,'') AS note
        FROM landlord_accreditations
        WHERE landlord_id = ?
        """,
        (lid,),
    ).fetchall()
    current = {row["accreditation_id"]: row["note"] for row in rows}

    if request.method == "POST":
        # Build a set of checked accreditation IDs from form
        checked_ids = set()
        for a in accreditations:
            key = f"accreditation_{a['id']}"
            if request.form.get(key) in ("1", "on", "true"):
                checked_ids.add(a["id"])

        # Upsert checked ones (with notes), delete unchecked ones
        for a in accreditations:
            aid = a["id"]
            notes = (request.form.get(f"extra_{aid}") or "").strip()

            if aid in checked_ids:
                # Insert or update
                if aid in current:
                    conn.execute(
                        """
                        UPDATE landlord_accreditations
                        SET note = ?
                        WHERE landlord_id = ? AND accreditation_id = ?
                        """,
                        (notes, lid, aid),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO landlord_accreditations (landlord_id, accreditation_id, note)
                        VALUES (?, ?, ?)
                        """,
                        (lid, aid, notes),
                    )
            else:
                # Remove if previously chosen
                if aid in current:
                    conn.execute(
                        "DELETE FROM landlord_accreditations WHERE landlord_id = ? AND accreditation_id = ?",
                        (lid, aid),
                    )

        conn.commit()
        conn.close()
        flash("Accreditations updated.", "ok")
        return redirect(url_for("landlord.landlord_accreditations"))

    # GET render
    conn.close()
    return render_template(
        "landlord_accreditations.html",
        profile=profile,
        schemes=accreditations,  # template still expects 'schemes'
        current=current,
    )
