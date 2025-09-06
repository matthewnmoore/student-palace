# admin/accreditations.py
from __future__ import annotations

import sqlite3
from flask import render_template, request, redirect, url_for, flash
from models import get_active_cities_safe  # not used here but keeps import parity style
from db import get_db
from . import bp, _is_admin

# ------------------------------------
# Schema safety (idempotent, add-only)
# ------------------------------------
def _ensure_accreditation_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accreditation_types(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            help_text TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS landlord_accreditations(
            landlord_id INTEGER NOT NULL,
            accreditation_id INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (landlord_id, accreditation_id),
            FOREIGN KEY (landlord_id) REFERENCES landlords(id) ON DELETE CASCADE,
            FOREIGN KEY (accreditation_id) REFERENCES accreditation_types(id) ON DELETE CASCADE
        )
    """)
    conn.commit()


def _slugify(name: str) -> str:
    s = (name or "").strip().lower()
    out = []
    prev_dash = False
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        else:
            if not prev_dash:
                out.append("-")
                prev_dash = True
    slug = "".join(out).strip("-") or "accreditation"
    return slug


# ----------------
# Admin pages
# ----------------
@bp.route("/accreditations", methods=["GET", "POST"])
def admin_accreditations():
    if not _is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_db()
    try:
        _ensure_accreditation_schema(conn)

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()

            if action == "add":
                name = (request.form.get("name") or "").strip()
                help_text = (request.form.get("help_text") or "").strip()
                active = 1 if (request.form.get("is_active") == "on") else 1  # default ON
                if not name:
                    flash("Name is required.", "error")
                else:
                    base = _slugify(name)
                    # ensure unique slug
                    slug = base
                    i = 2
                    while conn.execute(
                        "SELECT 1 FROM accreditation_types WHERE slug=?", (slug,)
                    ).fetchone():
                        slug = f"{base}-{i}"
                        i += 1
                    try:
                        # sort_order to end of list
                        row = conn.execute("SELECT COALESCE(MAX(sort_order),0) AS m FROM accreditation_types").fetchone()
                        next_sort = int(row["m"] if row and "m" in row.keys() else 0) + 10
                        conn.execute("""
                            INSERT INTO accreditation_types(name, slug, is_active, sort_order, help_text)
                            VALUES(?,?,?,?,?)
                        """, (name, slug, active, next_sort, help_text))
                        conn.commit()
                        flash(f"Added accreditation: {name}", "ok")
                    except sqlite3.IntegrityError:
                        flash("That accreditation already exists.", "error")

            elif action in ("activate", "deactivate"):
                try:
                    aid = int(request.form.get("id") or 0)
                except Exception:
                    aid = 0
                if aid:
                    val = 1 if action == "activate" else 0
                    conn.execute("UPDATE accreditation_types SET is_active=? WHERE id=?", (val, aid))
                    conn.commit()
                    flash("Status updated.", "ok")

            elif action == "delete":
                try:
                    aid = int(request.form.get("id") or 0)
                except Exception:
                    aid = 0
                if aid:
                    conn.execute("DELETE FROM accreditation_types WHERE id=?", (aid,))
                    conn.commit()
                    flash("Accreditation deleted.", "ok")

            elif action == "edit":
                # Inline edit for name/help_text
                try:
                    aid = int(request.form.get("id") or 0)
                except Exception:
                    aid = 0
                name = (request.form.get("name") or "").strip()
                help_text = (request.form.get("help_text") or "").strip()
                is_active = 1 if (request.form.get("is_active") == "on") else 0
                if aid and name:
                    # update name; keep slug stable unless empty (legacy)
                    row = conn.execute("SELECT slug FROM accreditation_types WHERE id=?", (aid,)).fetchone()
                    slug = (row["slug"] if row and "slug" in row.keys() else "") or _slugify(name)
                    # ensure slug unique if we just generated it
                    if not row or not row["slug"]:
                        base = slug
                        i = 2
                        while conn.execute(
                            "SELECT 1 FROM accreditation_types WHERE slug=? AND id<>?",
                            (slug, aid)
                        ).fetchone():
                            slug = f"{base}-{i}"
                            i += 1
                    conn.execute("""
                        UPDATE accreditation_types
                           SET name=?,
                               help_text=?,
                               is_active=?,
                               slug=?
                         WHERE id=?
                    """, (name, help_text, is_active, slug, aid))
                    conn.commit()
                    flash("Accreditation updated.", "ok")

            elif action == "reorder":
                # Accepts multiple sort_order[id]=value pairs
                # Form fields will be like order_<id>
                rows = conn.execute("SELECT id FROM accreditation_types").fetchall()
                ids = [int(r["id"]) for r in rows] if rows else []
                changed = 0
                for rid in ids:
                    key = f"order_{rid}"
                    try:
                        val = int(request.form.get(key) or 0)
                    except Exception:
                        val = 0
                    conn.execute("UPDATE accreditation_types SET sort_order=? WHERE id=?", (val, rid))
                    changed += 1
                conn.commit()
                if changed:
                    flash("Order saved.", "ok")

        items = conn.execute("""
            SELECT id, name, slug, is_active, sort_order, help_text
              FROM accreditation_types
             ORDER BY sort_order ASC, name ASC
        """).fetchall()

        return render_template("admin_accreditations.html", items=items)
    finally:
        conn.close()
