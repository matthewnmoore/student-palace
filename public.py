# public.py
from __future__ import annotations

from flask import Blueprint, render_template, request, abort, jsonify
from datetime import datetime as dt

# Import helpers from your models module
from models import get_active_city_names

# DB access
from db import get_db

# --- Blueprint ---
public_bp = Blueprint("public", __name__)

# --- Routes ---

@public_bp.route("/")
def index():
    """
    Home page: shows hero, search form, and featured card.
    Expects a list of city names for the selects and copy blocks.
    """
    cities = get_active_city_names(order_by_admin=True)

    # Simple featured stub (can be wired to DB later)
    featured = {
        "title": "Spacious 5-bed student house",
        "city": cities[0] if cities else "Leeds",
        "price_pppw": 135,
        "badges": ["Bills included", "Close to campus", "Wi-Fi"],
        "image": "",
        "link": "#",
        "generated_at": dt.utcnow().isoformat()
    }

    return render_template("index.html", cities=cities, featured=featured)


@public_bp.route("/search")
def search():
    """
    Basic search echo (DB wiring comes later).
    Keeps params compatible with current templates.
    """
    cities = get_active_city_names(order_by_admin=True)

    q = {
        "city": request.args.get("city", ""),
        "group_size": request.args.get("group_size", ""),
        "gender": request.args.get("gender", ""),
        "ensuite": "on" if request.args.get("ensuite") else "",
        "bills_included": "on" if request.args.get("bills_included") else "",
        "error": None
    }

    return render_template("search.html", query=q, cities=cities)


@public_bp.route("/p/<int:house_id>")
def property_public(house_id: int):
    """
    Public property detail page.
    Pulls the house, landlord (for verification badge), images, and rooms.
    Renders templates/property_public.html.
    """
    conn = get_db()

    # House
    house = conn.execute(
        "SELECT * FROM houses WHERE id=?", (house_id,)
    ).fetchone()
    if not house:
        conn.close()
        abort(404)

    # Landlord bits (for name, verification, profile link)
    ll = conn.execute(
        """
        SELECT lp.display_name, lp.public_slug, lp.is_verified, l.email
          FROM landlord_profiles lp
          JOIN landlords l ON l.id = lp.landlord_id
         WHERE lp.landlord_id = ?
        """,
        (house["landlord_id"],)
    ).fetchone()

    # Images (primary first, then order)
    try:
        images = conn.execute(
            """
            SELECT id,
                   COALESCE(filename, file_name) AS filename,
                   file_path,
                   width, height, bytes,
                   is_primary, sort_order, created_at
              FROM house_images
             WHERE house_id=?
             ORDER BY is_primary DESC, sort_order ASC, id ASC
            """,
            (house_id,)
        ).fetchall()
    except Exception:
        images = []

    # Rooms (for highlights: ensuites + availability + prices)
    try:
        rooms = conn.execute(
            """
            SELECT id, name, is_let, price_pcm, bed_size, room_size,
                   COALESCE(ensuite,0) AS ensuite,
                   COALESCE(has_ensuite,0) AS has_ensuite,
                   COALESCE(private_bathroom,0) AS private_bathroom,
                   description
              FROM rooms
             WHERE house_id=?
             ORDER BY id
            """,
            (house_id,)
        ).fetchall()
    except Exception:
        rooms = []

    conn.close()

    # View model for the template
    landlord = {
        "display_name": (ll["display_name"] if ll and "display_name" in ll.keys() else ""),
        "public_slug": (ll["public_slug"] if ll and "public_slug" in ll.keys() else ""),
        "is_verified": int(ll["is_verified"]) if (ll and "is_verified" in ll.keys()) else 0,
        "email": (ll["email"] if ll and "email" in ll.keys() else ""),
    }

    return render_template(
        "property_public.html",
        house=house,
        images=images,
        rooms=rooms,          # <-- IMPORTANT: pass rooms to template
        landlord=landlord,
    )


# -----------------------------
# DEBUG ENDPOINTS (read-only)
# -----------------------------

@public_bp.route("/debug/rooms/<int:house_id>")
def debug_rooms(house_id: int):
    """
    Show raw rows from the rooms table for a given house_id.
    Helpful to confirm the data actually exists and column names match.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM rooms WHERE house_id=? ORDER BY id ASC",
        (house_id,)
    ).fetchall()
    conn.close()
    return jsonify({
        "house_id": house_id,
        "count": len(rows),
        "rows": [dict(r) for r in rows],
    })


@public_bp.route("/debug/house/<int:house_id>")
def debug_house(house_id: int):
    """
    Quick snapshot of the house + landlord + counts of related rows.
    """
    conn = get_db()
    house = conn.execute("SELECT * FROM houses WHERE id=?", (house_id,)).fetchone()
    if not house:
        conn.close()
        return jsonify({"error": "house not found", "house_id": house_id}), 404

    landlord = conn.execute(
        """
        SELECT lp.display_name, lp.public_slug, lp.is_verified, l.email
          FROM landlord_profiles lp
          JOIN landlords l ON l.id = lp.landlord_id
         WHERE lp.landlord_id = ?
        """,
        (house["landlord_id"],)
    ).fetchone()

    images = conn.execute(
        "SELECT id, file_path, is_primary, sort_order FROM house_images WHERE house_id=? ORDER BY is_primary DESC, sort_order ASC, id ASC",
        (house_id,)
    ).fetchall()

    rooms = conn.execute(
        "SELECT id, name, is_let, ensuite, has_ensuite, private_bathroom, price_pcm FROM rooms WHERE house_id=? ORDER BY id ASC",
        (house_id,)
    ).fetchall()

    conn.close()
    return jsonify({
        "house": dict(house),
        "landlord": (dict(landlord) if landlord else None),
        "images_count": len(images),
        "rooms_count": len(rooms),
        "images_sample": [dict(r) for r in images[:5]],
        "rooms_sample": [dict(r) for r in rooms[:5]],
    })
