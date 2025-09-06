# landlord/delete.py
from __future__ import annotations

import os
from flask import redirect, url_for, flash
from db import get_db
from . import bp  # shared landlord blueprint

# Resolve /static from project root (one level up from /landlord)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")


def _abs_static_path(rel_path: str) -> str:
    """Convert stored relative static path (e.g. 'uploads/houses/abc.jpg')
    into a safe absolute path under /static."""
    rel_path = (rel_path or "").lstrip("/\\")
    abs_path = os.path.abspath(os.path.join(STATIC_ROOT, rel_path))
    if not abs_path.startswith(os.path.abspath(STATIC_ROOT) + os.sep):
        return ""  # refuse anything suspicious
    return abs_path


def _unlink_quiet(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass  # never block delete on file errors


# -----------------------------
# Gather file paths helpers
# -----------------------------
def _gather_house_file_paths(conn, house_id: int) -> list[str]:
    paths: list[str] = []

    # House images
    for r in conn.execute(
        "SELECT file_path FROM house_images WHERE house_id=?", (house_id,)
    ).fetchall():
        p = _abs_static_path(r["file_path"]);  p and paths.append(p)

    # Room images (join rooms -> room_images)
    for r in conn.execute("""
        SELECT ri.file_path
          FROM room_images ri
          JOIN rooms r ON r.id = ri.room_id
         WHERE r.house_id = ?
    """, (house_id,)).fetchall():
        p = _abs_static_path(r["file_path"]);  p and paths.append(p)

    # Floorplans (optional table)
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='house_floorplans'"
    ).fetchone():
        for r in conn.execute(
            "SELECT file_path FROM house_floorplans WHERE house_id=?", (house_id,)
        ).fetchall():
            p = _abs_static_path(r["file_path"]);  p and paths.append(p)

    # EPC / documents (optional table)
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='house_documents'"
    ).fetchone():
        for r in conn.execute(
            "SELECT file_path FROM house_documents WHERE house_id=?", (house_id,)
        ).fetchall():
            p = _abs_static_path(r["file_path"]);  p and paths.append(p)

    # De-dup while preserving order
    return list(dict.fromkeys(paths))


def _gather_room_file_paths(conn, room_id: int) -> list[str]:
    paths: list[str] = []
    for r in conn.execute(
        "SELECT file_path FROM room_images WHERE room_id=?", (room_id,)
    ).fetchall():
        p = _abs_static_path(r["file_path"]);  p and paths.append(p)
    return list(dict.fromkeys(paths))


# -----------------------------
# Routes
# -----------------------------
@bp.post("/landlord/houses/<int:house_id>/delete")
def delete_house(house_id: int):
    """Delete a house and everything under it (rooms, photos, plans, docs) + files."""
    conn = get_db()
    try:
        # 1) Gather file paths BEFORE rows disappear
        file_paths = _gather_house_file_paths(conn, house_id)

        # 2) Explicitly remove child rows (robust even if FKs are missing)
        conn.execute("""
            DELETE FROM room_images
             WHERE room_id IN (SELECT id FROM rooms WHERE house_id=?)
        """, (house_id,))
        conn.execute("DELETE FROM house_images WHERE house_id=?", (house_id,))
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='house_floorplans'").fetchone():
            conn.execute("DELETE FROM house_floorplans WHERE house_id=?", (house_id,))
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='house_documents'").fetchone():
            conn.execute("DELETE FROM house_documents WHERE house_id=?", (house_id,))
        conn.execute("DELETE FROM rooms WHERE house_id=?", (house_id,))

        # 3) Finally delete the house row
        cur = conn.execute("DELETE FROM houses WHERE id=?", (house_id,))
        if cur.rowcount == 0:
            flash("House not found.", "error")
            return redirect(url_for("landlord.landlord_houses"))

        conn.commit()

        # 4) Best-effort file cleanup (after DB success)
        for p in file_paths:
            _unlink_quiet(p)

        flash("House, rooms, photos, and documents deleted.", "success")
    except Exception as e:
        flash(f"Could not delete house: {e}", "error")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("landlord.landlord_houses"))


@bp.post("/landlord/rooms/<int:room_id>/delete")
def delete_room(room_id: int):
    """Delete a single room and its images (DB rows + files)."""
    conn = get_db()
    house_id = None
    try:
        # Find the room for redirect destination
        row = conn.execute(
            "SELECT id, house_id FROM rooms WHERE id=?", (room_id,)
        ).fetchone()
        if not row:
            flash("Room not found.", "error")
            return redirect(url_for("landlord.landlord_houses"))
        house_id = row["house_id"]

        # Gather files, then delete DB rows
        file_paths = _gather_room_file_paths(conn, room_id)
        conn.execute("DELETE FROM room_images WHERE room_id=?", (room_id,))
        conn.execute("DELETE FROM rooms WHERE id=?", (room_id,))
        conn.commit()

        # Best-effort file cleanup
        for p in file_paths:
            _unlink_quiet(p)

        flash("Room and its photos deleted.", "success")
    except Exception as e:
        flash(f"Could not delete room: {e}", "error")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return redirect(url_for("landlord.rooms_list", hid=house_id) if house_id else url_for("landlord.landlord_houses"))
