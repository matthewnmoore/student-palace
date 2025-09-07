# public.py
from __future__ import annotations

from flask import Blueprint, render_template, request, abort
from datetime import datetime as dt

# Helpers
from models import get_active_city_names
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

    # Simple featured stub (placeholder; can be wired to DB later)
    featured = {
        "title": "Spacious 5-bed student house",
        "city": cities[0] if cities else "Leeds",
        "price_pppw": 135,
        "badges": ["Bills included", "Close to campus", "Wi-Fi"],
        "image": "",
        "link": "#",
        "generated_at": dt.utcnow().isoformat(),
    }

    return render_template("index.html", cities=cities, featured=featured)


@public_bp.route("/search")
def search():
    """
    Basic search echo (DB wiring comes later).
    Keeps params compatible with current templates.
    """
    cities = get_active_city_names(order_by_admin=True)

    # Availability-related params are echoed back so we can start wiring future filtering
    q = {
        "city": request.args.get("city", ""),
        "group_size": request.args.get("group_size", ""),
        "gender": request.args.get("gender", ""),
        "ensuite": "on" if request.args.get("ensuite") else "",
        "bills_included": "on" if request.args.get("bills_included") else "",

        # --- NEW: availability fields (optional) ---
        # ISO yyyy-mm-dd expected if provided
        "available_from": request.args.get("available_from", ""),  # move-in on/after
        "let_until": request.args.get("let_until", ""),            # useful if searching for houses currently let until a date
        "currently_let": request.args.get("currently_let", ""),    # "on" if user ticks 'currently let'
        # ------------------------------------------------

        "error": None,
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

    # Landlord summary (for name, verification, profile link/email)
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

    # Rooms (only columns present in schema)
    try:
        rooms = conn.execute(
            """
            SELECT id, name, is_let, price_pcm, bed_size, room_size,
                   COALESCE(ensuite,0) AS ensuite,
                   description
              FROM rooms
             WHERE house_id=?
             ORDER BY id
            """,
            (house_id,)
        ).fetchall()
    except Exception:
        rooms = []

    # --- NEW: Features (feature1..feature5) + availability fields at house level ---
    def _haskey(row, key: str) -> bool:
        try:
            return key in row.keys()
        except Exception:
            return False

    # Collect up to 5 short features, skipping empties and trimming to 40 chars (UI limit)
    features = []
    for i in range(1, 6):
        k = f"feature{i}"
        if _haskey(house, k) and house[k]:
            txt = str(house[k]).strip()
            if txt:
                features.append(txt[:40])

    # House-level availability (if these columns exist in your schema)
    availability = {
        "currently_let": int(house["is_let"]) if _haskey(house, "is_let") and house["is_let"] is not None else 0,
        "available_from": house["available_from"] if _haskey(house, "available_from") else None,
        "let_until": house["let_until"] if _haskey(house, "let_until") else None,
    }
    # -------------------------------------------------------------------------------

    conn.close()

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
        rooms=rooms,
        landlord=landlord,

        # NEW context for the template
        features=features,
        availability=availability,
    )


@public_bp.route("/about")
def about():
    """Public About Us page."""
    return render_template("about.html")
