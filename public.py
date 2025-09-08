# public.py
from __future__ import annotations

from flask import Blueprint, render_template, request, abort
from datetime import datetime as dt, date

# Helpers
from models import get_active_city_names
from db import get_db

# --- Blueprint ---
public_bp = Blueprint("public", __name__)

# --- Utility: build card data for /properties ---

def _cover_for_house(conn, hid: int) -> str | None:
    """
    Return a static URL path for the house's cover image.
    Prefers is_primary=1, then sort_order, then id.
    Returns a value suitable to feed directly to <img src="{{ ... }}">
    """
    row = conn.execute(
        """
        SELECT file_path
          FROM house_images
         WHERE house_id=?
         ORDER BY is_primary DESC, sort_order ASC, id ASC
         LIMIT 1
        """,
        (hid,)
    ).fetchone()
    if not row or not row["file_path"]:
        return None
    fp = row["file_path"].lstrip("/")
    # If file_path already starts with "static/", browsers want "/static/..."
    return ("/" + fp) if fp.startswith("static/") else ("/static/" + fp)

def _room_rollups(conn, hid: int) -> dict:
    """
    Compute lightweight per-house rollups used on listing cards.
    - available_rooms_total = count rooms where is_let = 0
    - ensuites_available    = count rooms where ensuite=1 and is_let=0
    - from_price_pcm        = MIN(price_pcm) among available rooms (fallback to any rooms)
    - from_price_ppw        = derived ((pcm*12)//52) for display
    """
    # Available rooms
    r = conn.execute(
        "SELECT COUNT(*) AS c FROM rooms WHERE house_id=? AND COALESCE(is_let,0)=0",
        (hid,)
    ).fetchone()
    avail = int(r["c"] if r else 0)

    # Ensuites available
    r = conn.execute(
        "SELECT COUNT(*) AS c FROM rooms WHERE house_id=? AND COALESCE(is_let,0)=0 AND COALESCE(ensuite,0)=1",
        (hid,)
    ).fetchone()
    ens = int(r["c"] if r else 0)

    # From price (prefer available rooms, else any room)
    r = conn.execute(
        "SELECT MIN(NULLIF(price_pcm,0)) AS p FROM rooms WHERE house_id=? AND COALESCE(is_let,0)=0",
        (hid,)
    ).fetchone()
    p_avail = int(r["p"]) if (r and r["p"] is not None) else None

    if p_avail is None:
        r = conn.execute(
            "SELECT MIN(NULLIF(price_pcm,0)) AS p FROM rooms WHERE house_id=?",
            (hid,)
        ).fetchone()
        p_any = int(r["p"]) if (r and r["p"] is not None) else None
        base_pcm = p_any
    else:
        base_pcm = p_avail

    if base_pcm and base_pcm > 0:
        ppw = (base_pcm * 12) // 52
    else:
        ppw = None

    return {
        "available_rooms_total": avail,
        "ensuites_available": ens,
        "from_price_pcm": base_pcm,
        "from_price_ppw": ppw,
    }

def _house_cards(conn) -> list[dict]:
    """
    Pull all houses and shape them for the listing grid.
    No filtering yet — this is a visual baseline page.
    """
    rows = conn.execute(
        """
        SELECT id, title, city, address, letting_type, bills_option,
               COALESCE(available_rooms_total, 0) AS pre_avail,
               COALESCE(ensuites_available, 0)    AS pre_ens
          FROM houses
         ORDER BY id DESC
        """
    ).fetchall()

    cards = []
    for h in rows or []:
        hid = int(h["id"])
        cover = _cover_for_house(conn, hid)

        # Use precomputed rollups if you want; recompute to be safe/consistent:
        r = _room_rollups(conn, hid)

        cards.append({
            "id": hid,
            "title": h["title"],
            "city": h["city"],
            "address": h["address"],
            "letting_type": h["letting_type"],           # 'whole' or 'share'
            "bills_option": h["bills_option"],           # 'yes'/'some'/'no'
            "cover_url": cover,                          # may be None
            "available_rooms_total": r["available_rooms_total"],
            "ensuites_available": r["ensuites_available"],
            "from_price_pcm": r["from_price_pcm"],
            "from_price_ppw": r["from_price_ppw"],
        })
    return cards

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

    q = {
        "city": request.args.get("city", ""),
        "group_size": request.args.get("group_size", ""),
        "gender": request.args.get("gender", ""),
        "ensuite": "on" if request.args.get("ensuite") else "",
        "bills_included": "on" if request.args.get("bills_included") else "",

        # Availability fields (optional)
        "available_from": request.args.get("available_from", ""),
        "let_until": request.args.get("let_until", ""),
        "currently_let": request.args.get("currently_let", ""),
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

    # Rooms (include couples_ok + disabled_ok)
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

    # House-level availability (optional columns)
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


@public_bp.route("/properties")
def properties():
    """
    Simple 'all properties' listing for visual review.
    - No filtering yet (placeholders only).
    - Includes landlord_verified so the green tick can render in the card.
    - Computes cover image, from_price_pcm, and room/ensuite counts.
    """
    conn = get_db()
    cities = get_active_city_names(order_by_admin=True)

    # Academic year placeholders for the top bar (not wired)
    years = [{"value": f"{y}/{y+1}", "label": f"{y}/{y+1}"} for y in range(2025, 2025+5)]

    sql = """
    WITH cover AS (
      SELECT house_id, MIN(file_path) AS cover_path
        FROM house_images
       GROUP BY house_id
    ),
    price AS (
      SELECT house_id, MIN(NULLIF(price_pcm,0)) AS from_price_pcm
        FROM rooms
       GROUP BY house_id
    ),
    room_counts AS (
      SELECT house_id,
             COUNT(*) AS rooms_total,
             SUM(CASE WHEN COALESCE(is_let,0)=0 THEN 1 ELSE 0 END) AS rooms_available,
             SUM(CASE WHEN COALESCE(ensuite,0)=1 THEN 1 ELSE 0 END) AS ensuites_available
        FROM rooms
       GROUP BY house_id
    )
    SELECT h.id, h.title, h.address, h.city, h.letting_type, h.bedrooms_total,
           h.bills_option,
           COALESCE(rc.rooms_total,0)           AS rooms_total,
           COALESCE(rc.rooms_available,0)       AS available_rooms_total,
           COALESCE(rc.ensuites_available,0)    AS ensuites_available,
           p.from_price_pcm,
           c.cover_path,
           lp.is_verified                       AS landlord_verified
      FROM houses h
      LEFT JOIN room_counts      rc ON rc.house_id = h.id
      LEFT JOIN cover            c  ON c.house_id  = h.id
      LEFT JOIN price            p  ON p.house_id  = h.id
      LEFT JOIN landlord_profiles lp ON lp.landlord_id = h.landlord_id
     ORDER BY h.id DESC;
    """
    rows = conn.execute(sql).fetchall()
    conn.close()

    # Build result dicts the template expects
    from flask import url_for
    def make_cover_url(path):
        if not path:
            return None
        fp = path[7:] if path.startswith("static/") else path
        return url_for("static", filename=fp.lstrip("/"))

    results = []
    for r in rows:
        pcm = r["from_price_pcm"]
        ppw = round(pcm / 4.333) if pcm else None
        results.append({
            "id": r["id"],
            "title": r["title"],
            "address": r["address"],
            "city": r["city"],
            "letting_type": r["letting_type"],
            "bedrooms_total": r["bedrooms_total"],
            "bills_option": r["bills_option"],
            "ensuites_available": r["ensuites_available"],
            "available_rooms_total": r["available_rooms_total"],
            "rooms_total": r["rooms_total"],
            "from_price_pcm": pcm,
            "from_price_ppw": ppw,
            "cover_url": make_cover_url(r["cover_path"]),
            "landlord_verified": r["landlord_verified"],
        })

    return render_template(
        "properties_list.html",
        cities=cities,
        years=years,
        results=results,
    )

@public_bp.route("/about")
def about():
    """Public About Us page."""
    return render_template("about.html")
