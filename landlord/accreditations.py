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

    # Active schemes for landlords to choose from
    schemes = conn.execute(
        """
        SELECT id, name, 1 AS has_notes  -- toggle has_notes to 0 if you ever want no notes box
        FROM accreditation_schemes
        WHERE is_active = 1
        ORDER BY id ASC
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
    current = {row["scheme_id"]: row["extra_text"] for row in rows}

    if request.method == "POST":
        # Build a set of checked scheme IDs from form
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
                # Insert or update
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
                # Remove if previously chosen
                if sid in current:
                    conn.execute(
                        "DELETE FROM landlord_accreditations WHERE landlord_id = ? AND scheme_id = ?",
                        (lid, sid),
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
        schemes=schemes,
        current=current,
    )
