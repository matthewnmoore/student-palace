from __future__ import annotations

import os
from typing import Iterable, List
from flask import request, render_template, redirect, url_for, flash
from db import get_db
from . import bp, require_admin, _admin_token

# Resolve absolute /static path (project-root/static)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")

def _abs_static_path(rel_path: str) -> str:
    """Convert 'uploads/.../file.ext' into a safe absolute path under /static."""
    rel_path = (rel_path or "").lstrip("/\\")
    abs_path = os.path.abspath(os.path.join(STATIC_ROOT, rel_path))
    safe_root = os.path.abspath(STATIC_ROOT) + os.sep
    if abs_path.startswith(safe_root):
        return abs_path
    return ""  # refuse anything outside /static

def _unlink_quiet(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass

def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())

def _gather_house_file_paths(conn, house_id: int) -> List[str]:
    """All files tied to one house (house images, room images, floorplans, docs)."""
    paths: List[str] = []

    # House images
    for r in conn.execute("SELECT file_path FROM house_images WHERE house_id=?", (house_id,)).fetchall():
        p = _abs_static_path(r["file_path"]); p and paths.append(p)

    # Room images via rooms
    if _table_exists(conn, "room_images"):
        for r in conn.execute("""
            SELECT ri.file_path
              FROM room_images ri
              JOIN rooms r ON r.id = ri.room_id
             WHERE r.house_id = ?
        """, (house_id,)).fetchall():
            p = _abs_static_path(r["file_path"]); p and paths.append(p)

    # Floorplans (optional)
    if _table_exists(conn, "house_floorplans"):
        for r in conn.execute("SELECT file_path FROM house_floorplans WHERE house_id=?", (house_id,)).fetchall():
            p = _abs_static_path(r["file_path"]); p and paths.append(p)

    # Documents (optional)
    if _table_exists(conn, "house_documents"):
        for r in conn.execute("SELECT file_path FROM house_documents WHERE house_id=?", (house_id,)).fetchall():
            p = _abs_static_path(r["file_path"]); p and paths.append(p)

    # de-dup
    return list(dict.fromkeys(paths))

def _gather_landlord_file_paths(conn, landlord_id: int) -> List[str]:
    paths: List[str] = []
    house_ids = [r["id"] for r in conn.execute("SELECT id FROM houses WHERE landlord_id=?", (landlord_id,)).fetchall()]
    for hid in house_ids:
        paths.extend(_gather_house_file_paths(conn, hid))
    return list(dict.fromkeys(paths))

def _counts_for_landlord(conn, landlord_id: int) -> dict:
    """Return counts for a pre-delete summary screen."""
    counts = {
        "houses": 0, "rooms": 0,
        "house_images": 0, "room_images": 0,
        "documents": 0, "floorplans": 0,
    }
    counts["houses"] = conn.execute("SELECT COUNT(*) c FROM houses WHERE landlord_id=?", (landlord_id,)).fetchone()["c"]
    counts["rooms"] = conn.execute("""
        SELECT COUNT(*) c FROM rooms WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
    """, (landlord_id,)).fetchone()["c"]

    counts["house_images"] = conn.execute("""
        SELECT COUNT(*) c FROM house_images WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
    """, (landlord_id,)).fetchone()["c"]

    if _table_exists(conn, "room_images"):
        counts["room_images"] = conn.execute("""
            SELECT COUNT(*) c
              FROM room_images
             WHERE room_id IN (
                SELECT id FROM rooms WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
             )
        """, (landlord_id,)).fetchone()["c"]

    if _table_exists(conn, "house_documents"):
        counts["documents"] = conn.execute("""
            SELECT COUNT(*) c
              FROM house_documents
             WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
        """, (landlord_id,)).fetchone()["c"]

    if _table_exists(conn, "house_floorplans"):
        counts["floorplans"] = conn.execute("""
            SELECT COUNT(*) c
              FROM house_floorplans
             WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
        """, (landlord_id,)).fetchone()["c"]

    return counts

# -------------------------------------------------------------------
# STEP 1 — Confirm target (type landlord email or display name)
# -------------------------------------------------------------------
@bp.route("/landlords/<int:lid>/delete", methods=["GET", "POST"], endpoint="delete_landlord_start")
def delete_landlord_start(lid: int):
    r = require_admin()
    if r: return r

    conn = get_db()
    try:
        landlord = conn.execute("SELECT * FROM landlords WHERE id=?", (lid,)).fetchone()
        profile  = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
        if not landlord:
            flash("Landlord not found.", "error")
            return redirect(url_for("admin.admin_landlords"))

        if request.method == "POST":
            typed = (request.form.get("confirm_text") or "").strip().lower()
            email = (landlord["email"] or "").strip().lower()
            dname = (profile["display_name"].strip().lower() if profile and profile["display_name"] else "")
            if typed and (typed == email or (dname and typed == dname)):
                # move to step 2 (password)
                return redirect(url_for("admin.delete_landlord_password", lid=lid))
            flash("Confirmation text did not match email or display name.", "error")

        return render_template(
            "admin_delete_landlord_start.html",
            landlord=landlord, profile=profile
        )
    finally:
        conn.close()

# -------------------------------------------------------------------
# STEP 2 — Admin token (password) check
# -------------------------------------------------------------------
@bp.route("/landlords/<int:lid>/delete/password", methods=["GET", "POST"], endpoint="delete_landlord_password")
def delete_landlord_password(lid: int):
    r = require_admin()
    if r: return r

    conn = get_db()
    try:
        landlord = conn.execute("SELECT * FROM landlords WHERE id=?", (lid,)).fetchone()
        if not landlord:
            flash("Landlord not found.", "error")
            return redirect(url_for("admin.admin_landlords"))

        if request.method == "POST":
            token = (request.form.get("admin_token") or "").strip()
            if token and _admin_token() and token == _admin_token():
                # move to final step
                return redirect(url_for("admin.delete_landlord_final", lid=lid))
            flash("Invalid admin token.", "error")

        return render_template("admin_delete_landlord_password.html", landlord=landlord)
    finally:
        conn.close()

# -------------------------------------------------------------------
# STEP 3 — Final irreversible confirm (type DELETE)
# -------------------------------------------------------------------
@bp.route("/landlords/<int:lid>/delete/final", methods=["GET", "POST"], endpoint="delete_landlord_final")
def delete_landlord_final(lid: int):
    r = require_admin()
    if r: return r

    conn = get_db()
    try:
        landlord = conn.execute("SELECT * FROM landlords WHERE id=?", (lid,)).fetchone()
        profile  = conn.execute("SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)).fetchone()
        if not landlord:
            flash("Landlord not found.", "error")
            return redirect(url_for("admin.admin_landlords"))

        counts = _counts_for_landlord(conn, lid)

        if request.method == "POST":
            typed = (request.form.get("final_confirm") or "").strip().upper()
            if typed != "DELETE":
                flash("You must type DELETE exactly to proceed.", "error")
                return render_template("admin_delete_landlord_final.html",
                                       landlord=landlord, profile=profile, counts=counts)

            # gather files before rows disappear
            file_paths = _gather_landlord_file_paths(conn, lid)

            try:
                conn.execute("BEGIN")
                # child assets
                if _table_exists(conn, "room_images"):
                    conn.execute("""
                        DELETE FROM room_images
                         WHERE room_id IN (
                             SELECT id FROM rooms
                              WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
                         )
                    """, (lid,))
                conn.execute("""
                    DELETE FROM house_images
                     WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
                """, (lid,))
                if _table_exists(conn, "house_documents"):
                    conn.execute("""
                        DELETE FROM house_documents
                         WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
                    """, (lid,))
                if _table_exists(conn, "house_floorplans"):
                    conn.execute("""
                        DELETE FROM house_floorplans
                         WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
                    """, (lid,))

                # rooms and houses
                conn.execute("""
                    DELETE FROM rooms
                     WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
                """, (lid,))
                conn.execute("DELETE FROM houses WHERE landlord_id=?", (lid,))

                # profile then landlord
                conn.execute("DELETE FROM landlord_profiles WHERE landlord_id=?", (lid,))
                conn.execute("DELETE FROM landlords WHERE id=?", (lid,))

                conn.commit()
            except Exception as e:
                try: conn.rollback()
                except Exception: pass
                flash(f"Delete failed: {e}", "error")
                return render_template("admin_delete_landlord_final.html",
                                       landlord=landlord, profile=profile, counts=counts)

            # best-effort file cleanup
            for p in file_paths:
                _unlink_quiet(p)

            flash("Landlord and all associated data were deleted.", "ok")
            return redirect(url_for("admin.admin_landlords"))

        # GET
        return render_template("admin_delete_landlord_final.html",
                               landlord=landlord, profile=profile, counts=counts)
    finally:
        conn.close()
