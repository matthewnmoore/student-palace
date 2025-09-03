# public.py
from __future__ import annotations

import os
import html
from pathlib import Path
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

    # Rooms (only columns that exist in the DB schema)
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

    # Only columns that are guaranteed to exist
    rooms = conn.execute(
        "SELECT id, name, is_let, ensuite, price_pcm FROM rooms WHERE house_id=? ORDER BY id ASC",
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


# ---------------------------------------------
# HUMAN-FRIENDLY DB DUMP PAGE (read-only HTML)
# ---------------------------------------------
@public_bp.route("/show_me_the_data.html")
def show_me_the_data():
    """
    Debug page that lists all non-system tables in the DB with their fields and rows.
    Renders a simple HTML page with one <table> per DB table.
    """
    conn = get_db()

    # Get all non-system tables (skip sqlite_* internal tables)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()

    html_parts = ["<html><head><meta charset='utf-8'><title>DB Dump</title>"]
    html_parts.append(
        "<style>"
        "body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px;}"
        "h1{margin:0 0 10px;font-size:22px}"
        "h2{margin-top:36px;font-size:18px}"
        ".meta{color:#666;margin:0 0 20px}"
        "table{border-collapse:collapse;margin:10px 0 24px;width:100%;font-size:14px}"
        "th,td{border:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}"
        "th{background:#f7f7fb;font-weight:600}"
        "tbody tr:nth-child(even){background:#fafafa}"
        "code{background:#f3f3f6;padding:1px 4px;border-radius:4px}"
        "</style></head><body>"
    )
    html_parts.append("<h1>Student Palace – Database Dump</h1>")
    html_parts.append("<p class='meta'>Read-only view of all user tables.</p>")

    conn.row_factory = None  # ensure plain tuples for PRAGMA fallback if needed
    for t in tables:
        table_name = t["name"] if isinstance(t, dict) or hasattr(t, "keys") else t[0]

        # Columns (ordered by cid)
        pragma_rows = get_db().execute(f"PRAGMA table_info({table_name})").fetchall()
        cols = [row["name"] if hasattr(row, "keys") else row[1] for row in pragma_rows]
        if not cols:
            cur = get_db().execute(f"SELECT * FROM {table_name} LIMIT 0")
            cols = [d[0] for d in (cur.description or [])]

        # Rows
        rows = get_db().execute(f"SELECT * FROM {table_name}").fetchall()

        html_parts.append(f"<h2>Table: <code>{html.escape(table_name)}</code> ({len(rows)} rows)</h2>")
        col_list = ", ".join([f"<code>{html.escape(c)}</code>" for c in cols])
        html_parts.append(f"<div class='meta'>Columns: {col_list}</div>")

        html_parts.append("<table><thead><tr>")
        for col in cols:
            html_parts.append(f"<th>{html.escape(col)}</th>")
        html_parts.append("</tr></thead><tbody>")

        for r in rows:
            html_parts.append("<tr>")
            # r can be sqlite3.Row (dict-like)
            try:
                keys = r.keys()
                for col in cols:
                    val = r[col] if col in keys else ""
                    sval = "" if val is None else str(val)
                    html_parts.append(f"<td>{html.escape(sval)}</td>")
            except Exception:
                # tuple fallback
                for val in r:
                    sval = "" if val is None else str(val)
                    html_parts.append(f"<td>{html.escape(sval)}</td>")
            html_parts.append("</tr>")

        html_parts.append("</tbody></table>")

    html_parts.append("</body></html>")
    return "".join(html_parts)


# ----------------------------------------------------------
# NUKE FILES: delete uploaded images/docs from the filesystem
# ----------------------------------------------------------
def _candidate_upload_roots() -> list[Path]:
    """
    Return likely roots that contain uploaded house assets.
    """
    here = Path(__file__).resolve()
    roots = [
        here.parent / "static" / "uploads" / "houses",
        Path("/opt/render/project/src/static/uploads/houses"),  # Render default used elsewhere
    ]
    # Deduplicate & keep only existing dirs
    uniq = []
    seen = set()
    for p in roots:
        p = p.resolve()
        if str(p) not in seen and p.exists() and p.is_dir():
            uniq.append(p)
            seen.add(str(p))
    return uniq


@public_bp.route("/admin/debug/nuke_upload_files", methods=["POST", "GET"])
def nuke_upload_files():
    """
    Remove uploaded *files on disk* under static/uploads/houses/** (including epc/ if present).
    - POST is preferred.
    - GET requires ?confirm=1 to run (otherwise returns a preview of what would be deleted).
    """
    if request.method == "GET" and request.args.get("confirm") != "1":
        roots = [str(p) for p in _candidate_upload_roots()]
        return jsonify({
            "status": "dry-run",
            "message": "Add ?confirm=1 to perform deletion, or POST to this endpoint.",
            "paths_checked": roots
        })

    deleted_files = 0
    checked_paths = []
    errors = []

    for base in _candidate_upload_roots():
        checked_paths.append(str(base))
        try:
            # Delete files under the root (non-recursive then recursive to catch nested like epc/)
            for p in base.rglob("*"):
                try:
                    if p.is_file():
                        p.unlink()
                        deleted_files += 1
                except Exception as e:
                    errors.append(f"{p}: {e}")
        except Exception as e:
            errors.append(f"{base}: {e}")

    return jsonify({
        "status": "ok",
        "deleted_files": deleted_files,
        "paths_checked": checked_paths,
        "errors": errors,
    })
