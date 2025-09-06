# admin/cities.py
from __future__ import annotations

import sqlite3
import re
import time
import json
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError
from flask import render_template, request, redirect, url_for, flash, jsonify
from models import get_db
from . import bp, _is_admin

# ---------------------------
# Utilities
# ---------------------------

_PREFIX_SPLIT_RE = re.compile(r"\s*,\s*")
_PREFIX_NORMALISE_RE = re.compile(r"[^A-Z0-9]")

def _ensure_cities_schema(conn: sqlite3.Connection) -> None:
    """
    Ensure the cities table exists and includes postcode_prefixes TEXT.
    Non-destructive: add-only.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cities("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT UNIQUE NOT NULL,"
        " is_active INTEGER NOT NULL DEFAULT 1,"
        " postcode_prefixes TEXT NOT NULL DEFAULT ''"
        ")"
    )
    # Older DBs may not have postcode_prefixes; add it safely.
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(cities)").fetchall()]
        if "postcode_prefixes" not in cols:
            conn.execute("ALTER TABLE cities ADD COLUMN postcode_prefixes TEXT NOT NULL DEFAULT ''")
            conn.commit()
    except Exception:
        # If anything odd happens, we leave it; page will still work without prefixes.
        pass

def _normalise_prefixes_csv(raw: str) -> str:
    """
    Turn a user-entered CSV into a clean, uppercase, comma-separated string.
    e.g. 'cf, cf3 , CF10' -> 'CF,CF3,CF10'
    """
    if not raw:
        return ""
    items = _PREFIX_SPLIT_RE.split(raw.strip())
    clean = []
    seen = set()
    for it in items:
        it = (it or "").strip().upper()
        if not it:
            continue
        # Allow only A–Z and digits in prefixes
        it = _PREFIX_NORMALISE_RE.sub("", it)
        if not it or it in seen:
            continue
        seen.add(it)
        clean.append(it)
    # Sort by length then lexicographically for nice display
    clean.sort(key=lambda s: (len(s), s))
    return ",".join(clean)

def _extract_outward(postcode: str) -> str:
    """
    Given a full postcode string, return outward code (before the space).
    """
    pc = (postcode or "").strip().upper()
    if not pc:
        return ""
    parts = pc.split()
    return parts[0] if parts else pc

def _letters_prefix(outward: str) -> str:
    """
    Letters-only area prefix from an outward code, e.g. 'CF10' -> 'CF', 'LS'->'LS'.
    """
    m = re.match(r"^[A-Z]+", outward)
    return m.group(0) if m else ""

# Simple in-process cache for suggestions (city -> (timestamp, [prefixes]))
_SUGGEST_CACHE: dict[str, tuple[float, list[str]]] = {}
_SUGGEST_TTL_SECONDS = 24 * 60 * 60  # 24h

def _get_live_prefix_suggestions(city: str, timeout: float = 3.0) -> list[str]:
    """
    Query postcodes.io for a city name and return a list of suggested prefixes
    (outward codes + their letter area). Best-effort, suitable for suggestions.
    """
    city = (city or "").strip()
    if not city:
        return []

    # Cache check
    cached = _SUGGEST_CACHE.get(city.lower())
    now = time.time()
    if cached and (now - cached[0] < _SUGGEST_TTL_SECONDS):
        return cached[1][:]

    prefixes: set[str] = set()

    # We use the /postcodes search endpoint as a lightweight way to harvest outwards.
    # Example: https://api.postcodes.io/postcodes?limit=100&q=Cardiff
    try:
        params = urlencode({"limit": 100, "q": city})
        url = f"https://api.postcodes.io/postcodes?{params}"
        req = Request(url, headers={"User-Agent": "StudentPalace/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = (data or {}).get("result") or []
            for item in results:
                pc_full = (item or {}).get("postcode") or ""
                outward = _extract_outward(pc_full)
                if outward:
                    prefixes.add(outward.upper())
                    area = _letters_prefix(outward)
                    if area:
                        prefixes.add(area)
    except URLError:
        # Network hiccup or API down → just return empty (admin can type manually)
        pass
    except Exception:
        # Any unexpected format → keep it graceful
        pass

    # Normalise / sort
    clean = []
    seen = set()
    for p in prefixes:
        p = p.strip().upper()
        if not p or p in seen:
            continue
        seen.add(p)
        clean.append(p)
    clean.sort(key=lambda s: (len(s), s))

    # Cap to something sensible for UI; admin can edit anyway
    clean = clean[:40]

    # Cache
    _SUGGEST_CACHE[city.lower()] = (now, clean[:])
    return clean

# ---------------------------
# Routes
# ---------------------------

@bp.route("/cities", methods=["GET", "POST"])
def admin_cities():
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_db()
    try:
        _ensure_cities_schema(conn)

        if request.method == "POST":
            action = request.form.get("action") or ""

            if action == "add":
                name = (request.form.get("name") or "").strip()
                raw_prefixes = request.form.get("postcode_prefixes") or ""
                prefixes = _normalise_prefixes_csv(raw_prefixes)

                if name:
                    try:
                        # Ensure table exists with latest columns (idempotent)
                        _ensure_cities_schema(conn)
                        conn.execute(
                            "INSERT INTO cities(name,is_active,postcode_prefixes) VALUES(?,?,?)",
                            (name, 1, prefixes),
                        )
                        conn.commit()
                        flash(f"Added city: {name}", "ok")
                    except sqlite3.IntegrityError:
                        flash("That city already exists.", "error")

            elif action in ("activate", "deactivate", "delete"):
                try:
                    cid = int(request.form.get("city_id") or 0)
                except Exception:
                    cid = 0
                if cid:
                    if action == "delete":
                        conn.execute("DELETE FROM cities WHERE id=?", (cid,))
                        conn.commit()
                        flash("City deleted.", "ok")
                    else:
                        new_val = 1 if action == "activate" else 0
                        conn.execute(
                            "UPDATE cities SET is_active=? WHERE id=?", (new_val, cid)
                        )
                        conn.commit()
                        flash("City updated.", "ok")

        rows = conn.execute(
            "SELECT id, name, is_active, COALESCE(postcode_prefixes,'') AS postcode_prefixes "
            "FROM cities ORDER BY name ASC"
        ).fetchall()
        return render_template("admin_cities.html", cities=rows)
    finally:
        conn.close()

@bp.route("/cities/suggest_prefixes")
def admin_cities_suggest_prefixes():
    """
    Admin-only JSON endpoint returning live postcode prefix suggestions
    for a given city name. Example:
      GET /admin/cities/suggest_prefixes?city=Cardiff
      -> { "prefixes": ["CF", "CF3", "CF5", "CF10", ...] }
    """
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    city = request.args.get("city", "").strip()
    if not city:
        return jsonify({"prefixes": [], "ok": True})

    prefixes = _get_live_prefix_suggestions(city)
    return jsonify({"prefixes": prefixes, "ok": True})

# ---------------------------
# NEW: Edit City route
# ---------------------------

@bp.route("/cities/<int:cid>/edit", methods=["GET", "POST"])
def admin_city_edit(cid: int):
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_db()
    try:
        _ensure_cities_schema(conn)
        city = conn.execute(
            "SELECT id, name, is_active, COALESCE(postcode_prefixes,'') AS postcode_prefixes "
            "FROM cities WHERE id=?", (cid,)
        ).fetchone()

        if not city:
            flash("City not found.", "error")
            return redirect(url_for("admin.admin_cities"))

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            raw_prefixes = request.form.get("postcode_prefixes") or ""
            prefixes = _normalise_prefixes_csv(raw_prefixes)

            if not name:
                flash("City name is required.", "error")
            else:
                conn.execute(
                    "UPDATE cities SET name=?, postcode_prefixes=? WHERE id=?",
                    (name, prefixes, cid)
                )
                conn.commit()
                flash("City updated.", "ok")
                return redirect(url_for("admin.admin_cities"))

        return render_template("admin_city_edit.html", city=city)
    finally:
        conn.close()
