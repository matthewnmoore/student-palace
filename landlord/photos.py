from flask import render_template, redirect, url_for, flash
from utils import current_landlord_id, require_landlord, owned_house_or_none
from db import get_db

from . import landlord_bp


# -------------------------------
# Photos (Phase 1: UI only)
# -------------------------------

@landlord_bp.route("/landlord/houses/<int:hid>/photos")
def house_photos(hid):
    """Render the photos page for a house (no upload/processing yet)."""
    r = require_landlord()
    if r:
        return r

    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    rows = conn.execute("""
        SELECT id, filename, is_primary
          FROM house_images
         WHERE house_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (hid,)).fetchall()

    # Limit: 5 photos per house (UI only; upload still stubbed)
    max_images = 5
    current_count = len(rows)

    images = []
    for r_ in rows:
        images.append({
            "id": r_["id"],
            "is_primary": bool(r_["is_primary"]),
            "file_path": f"uploads/houses/{r_['filename']}",
        })
    conn.close()

    remaining = max(0, max_images - current_count)
    return render_template(
        "house_photos.html",
        house=house,
        images=images,
        max_images=max_images,
        remaining=remaining
    )


@landlord_bp.route("/landlord/houses/<int:hid>/photos/upload", methods=["POST"])
def house_photos_upload(hid):
    """Stub: uploading disabled until Phase 2 processing is added."""
    r = require_landlord()
    if r:
        return r
    flash("Photo uploading will be enabled in the next step.", "error")
    return redirect(url_for("landlord.house_photos", hid=hid))


@landlord_bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/primary", methods=["POST"])
def house_photos_primary(hid, img_id):
    """Stub: marking primary will be enabled in the next step."""
    r = require_landlord()
    if r:
        return r
    flash("Setting a primary photo will be enabled in the next step.", "error")
    return redirect(url_for("landlord.house_photos", hid=hid))


@landlord_bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/delete", methods=["POST"])
def house_photos_delete(hid, img_id):
    """Stub: deleting will be enabled in the next step."""
    r = require_landlord()
    if r:
        return r
    flash("Deleting photos will be enabled in the next step.", "error")
    return redirect(url_for("landlord.house_photos", hid=hid))
