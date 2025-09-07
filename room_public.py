# room_public.py
from __future__ import annotations
from flask import Blueprint, render_template, abort
from db import get_db

room_public_bp = Blueprint("room_public", __name__)

@room_public_bp.route("/r/<int:room_id>")
def room_public(room_id: int):
    conn = get_db()

    room = conn.execute("""
        SELECT id, house_id, name, is_let, price_pcm, bed_size, room_size,
               COALESCE(ensuite,0) AS ensuite,
               COALESCE(couples_ok,0) AS couples_ok,
               COALESCE(disabled_ok,0) AS disabled_ok,
               description
        FROM rooms WHERE id=?
    """, (room_id,)).fetchone()
    if not room:
        conn.close()
        abort(404)

    house = conn.execute("SELECT * FROM houses WHERE id=?", (room["house_id"],)).fetchone()

    ll = conn.execute("""
        SELECT lp.display_name, lp.public_slug, lp.is_verified, l.email
          FROM landlord_profiles lp
          JOIN landlords l ON l.id = lp.landlord_id
         WHERE lp.landlord_id = ?
    """, (house["landlord_id"],)).fetchone() if house else None

    images = conn.execute("""
        SELECT id,
               COALESCE(filename, file_name) AS filename,
               file_path, width, height, bytes,
               is_primary, sort_order, created_at
          FROM room_images
         WHERE room_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (room_id,)).fetchall()

    conn.close()

    landlord = {
        "display_name": (ll["display_name"] if ll and "display_name" in ll.keys() else ""),
        "public_slug": (ll["public_slug"] if ll and "public_slug" in ll.keys() else ""),
        "is_verified": int(ll["is_verified"]) if (ll and "is_verified" in ll.keys()) else 0,
        "email": (ll["email"] if ll and "email" in ll.keys() else ""),
    }

    # Reuse house template style but with a room-focused template
    return render_template(
        "room_public.html",
        room=room,
        house=house,
        images=images,
        landlord=landlord,
    )
