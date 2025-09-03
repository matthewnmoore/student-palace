# public/property_public.py
from __future__ import annotations

from flask import Blueprint, render_template, abort, url_for
from db import get_db

bp = Blueprint("public", __name__)  # register this in app.py (app.register_blueprint(public.property_public.bp))

def _fetch_house_bundle(conn, hid: int):
    house = conn.execute(
        "SELECT * FROM houses WHERE id=?",
        (hid,),
    ).fetchone()
    if not house:
        return None

    landlord = conn.execute(
        """
        SELECT lp.display_name, lp.public_slug, lp.is_verified, l.email
          FROM landlord_profiles lp
          JOIN landlords l ON l.id = lp.landlord_id
         WHERE lp.landlord_id=?
        """,
        (house["landlord_id"],),
    ).fetchone()

    images = conn.execute(
        """
        SELECT id,
               COALESCE(filename, file_name) AS fname,
               file_path, width, height, bytes,
               is_primary, sort_order, created_at
          FROM house_images
         WHERE house_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
         LIMIT 5
        """,
        (hid,),
    ).fetchall()

    rooms = conn.execute(
        """
        SELECT *
          FROM rooms
         WHERE house_id=?
         ORDER BY is_let ASC, name ASC, id ASC
        """,
        (hid,),
    ).fetchall()

    return dict(house=house, landlord=landlord, images=images, rooms=rooms)

@bp.route("/p/<int:hid>")
def property_public(hid: int):
    conn = get_db()
    bundle = _fetch_house_bundle(conn, hid)
    conn.close()

    if not bundle:
        return render_template("property_public.html", house=None), 404

    # Light massaging for template convenience
    house = dict(bundle["house"])
    landlord = dict(bundle["landlord"]) if bundle["landlord"] else {}

    # Bills helper text
    bills_option = (house.get("bills_option") or "no").lower()
    if bills_option == "yes":
        bills_label = "All bills included"
    elif bills_option == "some":
        bills_label = "Some bills included"
    else:
        bills_label = "Bills not included"

    # EPC badge text (optional)
    epc = (house.get("epc_rating") or "").strip().upper()
    epc_label = f"EPC {epc}" if epc in ("A","B","C","D","E","F","G") else ""

    ctx = dict(
        house=house,
        landlord=landlord,
        images=bundle["images"],
        rooms=bundle["rooms"],
        bills_label=bills_label,
        epc_label=epc_label,
    )
    return render_template("property_public.html", **ctx)
