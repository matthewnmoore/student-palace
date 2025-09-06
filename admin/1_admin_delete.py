# admin/admin_delete.py
from __future__ import annotations

import os
from flask import request, render_template, redirect, url_for, flash
from . import bp, require_admin, _admin_token
from db import get_db

# Resolve /static from project root (one level up from /admin)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")


def _abs_static_path(rel_path: str) -> str:
    """Convert a stored relative /static path into a safe absolute path under /static."""
    rel_path = (rel_path or "").lstrip("/\\")
    abs_path = os.path.abspath(os.path.join(STATIC_ROOT, rel_path))
    # refuse anything that escapes /static
    if not abs_path.startswith(os.path.abspath(STATIC_ROOT) + os.sep):
        return ""
    return abs_path


def _unlink_quiet(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        # never block deletion on file errors
        pass


def _gather_all_landlord_files(conn, landlord_id: int) -> list[str]:
    """
    Collect every file path under /static linked to this landlord:
      - house_images (all houses owned by landlord)
      - room_images (via rooms join)
      - optional house_floorplans
      - optional house_documents
      - optional landlord profile media (logo_path, photo_path)
    Return a de-duplicated list of ABSOLUTE paths under STATIC_ROOT.
    """
    paths: list[str] = []

    # House images
    for r in conn.execute("""
        SELECT hi.file_path
          FROM house_images hi
          JOIN houses h ON h.id = hi.house_id
         WHERE h.landlord_id=?
    """, (landlord_id,)).fetchall():
        p = _abs_static_path(r["file_path"]); p and paths.append(p)

    # Room images
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='room_images'").fetchone():
        for r in conn.execute("""
            SELECT ri.file_path
              FROM room_images ri
              JOIN rooms r ON r.id = ri.room_id
              JOIN houses h ON h.id = r.house_id
             WHERE h.landlord_id=?
        """, (landlord_id,)).fetchall():
            p = _abs_static_path(r["file_path"]); p and paths.append(p)

    # Floorplans (optional)
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='house_floorplans'").fetchone():
        for r in conn.execute("""
            SELECT fp.file_path
              FROM house_floorplans fp
              JOIN houses h ON h.id = fp.house_id
             WHERE h.landlord_id=?
        """, (landlord_id,)).fetchall():
            p = _abs_static_path(r["file_path"]); p and paths.append(p)

    # Documents/EPC (optional)
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='house_documents'").fetchone():
        for r in conn.execute("""
            SELECT d.file_path
              FROM house_documents d
              JOIN houses h ON h.id = d.house_id
             WHERE h.landlord_id=?
        """, (landlord_id,)).fetchall():
            p = _abs_static_path(r["file_path"]); p and paths.append(p)

    # Landlord profile media (optional columns)
    prof = conn.execute("SELECT logo_path, photo_path FROM landlord_profiles WHERE landlord_id=?", (landlord_id,)).fetchone()
    if prof:
        for key in ("logo_path", "photo_path"):
            p = _abs_static_path((prof[key] if key in prof.keys() else "") or "")
            p and paths.append(p)

    # De-dup while preserving order
    return list(dict.fromkeys(paths))


def _counts_snapshot(conn, landlord_id: int) -> dict:
    """Small snapshot for the confirmation page."""
    houses = conn.execute("SELECT COUNT(*) AS c FROM houses WHERE landlord_id=?", (landlord_id,)).fetchone()["c"]
    rooms = conn.execute("""
        SELECT COUNT(*) AS c
          FROM rooms r
          JOIN houses h ON h.id = r.house_id
         WHERE h.landlord_id=?
    """, (landlord_id,)).fetchone()["c"]
    photos = conn.execute("""
        SELECT COUNT(*) AS c
          FROM house_images hi
          JOIN houses h ON h.id = hi.house_id
         WHERE h.landlord_id=?
    """, (landlord_id,)).fetchone()["c"]
    return {"houses": houses, "rooms": rooms, "photos": photos}


@bp.get("/landlords/<int:lid>/delete", endpoint="delete_landlord_start")
def delete_landlord_start(lid: int):
    r = require_admin()
    if r: return r

    conn = get_db()
    try:
        landlord = conn.execute("SELECT * FROM landlords WHERE id=?", (lid,)).fetchone()
        if not landlord:
            flash("Landlord not found.", "error")
            return redirect(url_for("admin.admin_landlords"))

        counts = _counts_snapshot(conn, lid)
        return render_template("admin_confirm_delete_landlord.html",
                               landlord=landlord, counts=counties if (counties:=counts) else counts)
    finally:
        conn.close()


@bp.post("/landlords/<int:lid>/delete/confirm", endpoint="delete_landlord_confirm2")
def delete_landlord_confirm2(lid: int):
    r = require_admin()
    if r: return r

    token = (request.form.get("admin_token") or "").strip()
    if not _admin_token() or token != _admin_token():
        flash("Admin password/token incorrect.", "error")
        return redirect(url_for("admin.delete_landlord_start", lid=lid))

    # move to step 3 (type the landlord email to proceed)
    return redirect(url_for("admin.delete_landlord_verify", lid=lid))


@bp.route("/landlords/<int:lid>/delete/verify", methods=["GET", "POST"], endpoint="delete_landlord_verify")
def delete_landlord_verify(lid: int):
    r = require_admin()
    if r: return r

    conn = get_db()
    try:
        landlord = conn.execute("SELECT * FROM landlords WHERE id=?", (lid,)).fetchone()
        if not landlord:
            flash("Landlord not found.", "error")
            return redirect(url_for("admin.admin_landlords"))

        if request.method == "GET":
            return render_template("admin_confirm_delete_landlord_verify.html", landlord=landlord)

        # POST – final check (must type landlord email exactly)
        typed = (request.form.get("confirm_text") or "").strip().lower()
        if typed != (landlord["email"] or "").strip().lower():
            flash("Confirmation text did not match the landlord’s email.", "error")
            return redirect(url_for("admin.delete_landlord_verify", lid=lid))

        # Gather files first
        file_paths = _gather_all_landlord_files(conn, lid)

        # Delete dependent rows (be explicit for safety)
        # Room images (if table exists)
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='room_images'").fetchone():
            conn.execute("""
                DELETE FROM room_images
                 WHERE room_id IN (
                    SELECT r.id
                      FROM rooms r
                      JOIN houses h ON h.id = r.house_id
                     WHERE h.landlord_id=?)
            """, (lid,))

        # House images
        conn.execute("""
            DELETE FROM house_images
             WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
        """, (lid,))

        # Floorplans (optional)
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='house_floorplans'").fetchone():
            conn.execute("""
                DELETE FROM house_floorplans
                 WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
            """, (lid,))

        # Documents (optional)
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='house_documents'").fetchone():
            conn.execute("""
                DELETE FROM house_documents
                 WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
            """, (lid,))

        # Rooms, then Houses, then Profile, then Landlord
        conn.execute("""
            DELETE FROM rooms
             WHERE house_id IN (SELECT id FROM houses WHERE landlord_id=?)
        """, (lid,))
        conn.execute("DELETE FROM houses WHERE landlord_id=?", (lid,))
        conn.execute("DELETE FROM landlord_profiles WHERE landlord_id=?", (lid,))
        conn.execute("DELETE FROM landlords WHERE id=?", (lid,))
        conn.commit()

        # Best-effort file unlink
        for p in file_paths:
            _unlink_quiet(p)

        return render_template("admin_delete_done.html",
                               title="Landlord deleted",
                               message="The landlord and all related houses, rooms, images, and documents were deleted.")
    except Exception as e:
        flash(f"Delete failed: {e}", "error")
        return redirect(url_for("admin.admin_landlords"))
    finally:
        try:
            conn.close()
        except Exception:
            pass
