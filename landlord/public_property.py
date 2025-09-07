from flask import Blueprint, render_template, abort
from db import get_db

public_property_bp = Blueprint("public_property", __name__)

@public_property_bp.route("/p/<int:house_id>")
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

    # Landlord summary
    ll = conn.execute(
        """
        SELECT lp.display_name, lp.public_slug, lp.is_verified, l.email
          FROM landlord_profiles lp
          JOIN landlords l ON l.id = lp.landlord_id
         WHERE lp.landlord_id = ?
        """,
        (house["landlord_id"],)
    ).fetchone()

    # Images
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

    # Rooms
    try:
        rooms = conn.execute(
            """
            SELECT id,
                   name,
                   is_let,
                   price_pcm,
                   bed_size,
                   room_size,
                   COALESCE(ensuite, 0)     AS ensuite,
                   COALESCE(couples_ok, 0)  AS couples_ok,
                   COALESCE(disabled_ok, 0) AS disabled_ok,
                   description
              FROM rooms
             WHERE house_id=?
             ORDER BY id
            """,
            (house_id,)
        ).fetchall()
    except Exception:
        rooms = []

    # Features (feature1..feature5)
    def _haskey(row, key: str) -> bool:
        try:
            return key in row.keys()
        except Exception:
            return False

    features = []
    for i in range(1, 6):
        k = f"feature{i}"
        if _haskey(house, k) and house[k]:
            txt = str(house[k]).strip()
            if txt:
                features.append(txt[:40])

    availability = {
        "currently_let": int(house["is_let"]) if _haskey(house, "is_let") and house["is_let"] is not None else 0,
        "available_from": house["available_from"] if _haskey(house, "available_from") else None,
        "let_until": house["let_until"] if _haskey(house, "let_until") else None,
    }

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
        features=features,
        availability=availability,
    )
