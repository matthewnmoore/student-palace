# landlord/delete.py
from __future__ import annotations

import os
from flask import redirect, url_for, flash
from db import get_db

# Use the shared landlord blueprint defined in landlord/__init__.py
from . import bp

# Resolve /static from project root (one level up from /landlord)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")


def _abs_static_path(rel_path: str) -> str:
    """
    Convert a stored relative static path (e.g. 'uploads/houses/abc.jpg')
    into a safe absolute path under /static.
    """
    rel_path = (rel_path or "").lstrip("/\\")
    abs_path = os.path.abspath(os.path.join(STATIC_ROOT, rel_path))
    # safety: ensure we stay inside STATIC_ROOT
    if not abs_path.startswith(os.path.abspath(STATIC_ROOT) + os.sep):
        return ""  # refuse anything suspicious
    return abs_path


def _gather_house_file_paths(conn, house_id: int) -> list[str]:
    paths: list[str] = []

    # House images
    for r in conn.execute(
        "SELECT file_path FROM house_images WHERE house_id=?", (house_id,)
    ).fetchall():
        p = _abs_static_path(r["file_path"])
        if p:
            paths.append(p)

    # Room images (join rooms -> room_images)
    for r in conn.execute("""
        SELECT ri.file_path
          FROM room_images ri
          JOIN rooms r ON r.id = ri.room_id
         WHERE r.house_id = ?
    """, (house_id,)).fetchall():
        p = _abs_static_path(r["file_path"])
        if p:
            paths.append(p)

    # Floorplans (table may not exist on very old DBs)
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='house_floorplans'"
    ).fetchone():
        for r in conn.execute(
            "SELECT file_path FROM house_floorplans WHERE house_id=?", (house_id,)
        ).fetchall():
            p = _abs_static_path(r["file_path"])
            if p:
                paths.append(p)

    # EPC / documents (optional table)
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='house_documents'"
    ).fetchone():
        for r in conn.execute(
            "SELECT file_path FROM house_documents WHERE house_id=?", (house_id,)
        ).fetchall():
            p = _abs_static_path(r["file_path"])
            if p:
                paths.append(p)

    # De-dup while preserving order
    return list(dict.fromkeys(paths))


def _unlink_quiet(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        # swallow file errors; we don't want to block the delete
        pass


@bp.post("/landlord/houses/<int:house_id>/delete")
def delete_house(house_id: int):
    # (Optional) CSRF check if you use one:
    # csrf.protect()
    conn = get_db()
    try:
        # 1) Gather file paths BEFORE rows disappear via cascade
        file_paths = _gather_house_file_paths(conn, house_id)

        # 2) Delete the house -> cascades remove children (images, rooms, etc.)
        cur = conn.execute("DELETE FROM houses WHERE id=?", (house_id,))
        if cur.rowcount == 0:
            flash("House not found.", "error")
            return redirect(url_for("landlord.landlord_houses"))

        # 3) Best-effort file cleanup (after DB success)
        for p in file_paths:
            _unlink_quiet(p)

        flash("House and related data deleted.", "success")
    except Exception as e:
        flash(f"Could not delete house: {e}", "error")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("landlord.landlord_houses"))
