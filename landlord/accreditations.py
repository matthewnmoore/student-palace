# landlord/accreditations.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils import require_landlord, current_landlord_id
from . import bp


@bp.route("/landlord/accreditations", methods=["GET", "POST"])
def landlord_accreditations():
    """
    Landlord can tick accreditations and add an optional note.
    Uses:
      - accreditation_types(id, name, help_text, is_active, sort_order)
      - landlord_accreditations(landlord_id, accreditation_id, note, extra_text)
    """
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()

    conn = get_db()

    # Landlord profile (for the verified banner)
    profile = conn.execute(
        "SELECT * FROM landlord_profiles WHERE landlord_id = ?",
        (lid,),
    ).fetchone()

    # List of active accreditations to choose from
    accreditations = conn.execute(
        """
        SELECT
            id,
            name,
            help_text,
            is_active,
            sort_order,
            1 AS has_notes
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
        # Which boxes were checked?
        checked_ids = set()
        for a in accreditations:
            key = f"accreditation_{a['id']}"
            if request.form.get(key) in ("1", "on", "true"):
                checked_ids.add(int(a["id"]))

        # Upsert checked items (with note), delete unchecked
        for a in accreditations:
            aid = int(a["id"])
            note_val = (request.form.get(f"note_{aid}") or "").strip()

            if aid in checked_ids:
                if aid in current:
                    # Update existing
                    conn.execute(
                        """
                        UPDATE landlord_accreditations
                           SET note = ?
                         WHERE landlord_id = ? AND accreditation_id = ?
                        """,
                        (note_val, lid, aid),
                    )
                else:
                    # Insert new
                    conn.execute(
                        """
                        INSERT INTO landlord_accreditations (landlord_id, accreditation_id, note)
                        VALUES (?, ?, ?)
                        """,
                        (lid, aid, note_val),
                    )
            else:
                # Remove if previously chosen
                if aid in current:
                    conn.execute(
                        """
                        DELETE FROM landlord_accreditations
                         WHERE landlord_id = ? AND accreditation_id = ?
                        """,
                        (lid, aid),
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
        schemes=accreditations,     # template expects 'schemes'
        current=current,            # {accreditation_id: note}
        selected_ids=selected_ids,  # keep checkmarks
    )
