# admin/images.py
from __future__ import annotations

import os
from flask import render_template, request, redirect, url_for, flash
from models import get_db
from image_helpers import file_abs_path
from . import bp, require_admin


@bp.route("/images")
def admin_images():
    """
    Lists all house images with on-disk existence status.

    Query params:
      - broken=1     -> only show rows whose files are missing on disk
      - page=N       -> pagination (1-based)
      - limit=M      -> page size (default 50, max 200)
    """
    r = require_admin()
    if r:
        return r

    broken_only = (request.args.get("broken") == "1")

    # Parse page/limit safely
    try:
        page = int(request.args.get("page", 1))
    except Exception:
        page = 1
    if page < 1:
        page = 1

    try:
        limit = int(request.args.get("limit", 50))
    except Exception:
        limit = 50
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    offset = (page - 1) * limit

    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM house_images").fetchone()["c"]

        rows = conn.execute("""
            SELECT id, house_id,
                   COALESCE(filename, file_name) AS filename,
                   file_path, width, height, bytes,
                   is_primary, sort_order, created_at
              FROM house_images
             ORDER BY id DESC
             LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()

        items = []
        for r_ in rows:
            fname = r_["filename"]
            exists = os.path.exists(file_abs_path(fname))
            if (not broken_only) or (broken_only and not exists):
                items.append({
                    "id": r_["id"],
                    "house_id": r_["house_id"],
                    "filename": fname,
                    "file_path": r_["file_path"],
                    "exists": exists,
                    "width": r_["width"],
                    "height": r_["height"],
                    "bytes": r_["bytes"],
                    "is_primary": int(r_["is_primary"]) == 1,
                    "sort_order": r_["sort_order"],
                    "created_at": r_["created_at"],
                })

        return render_template(
            "admin_images.html",
            items=items,
            page=page,
            limit=limit,
            total=total,
            broken_only=broken_only
        )
    finally:
        conn.close()


@bp.route("/images/<int:img_id>/delete", methods=["POST"])
def admin_images_delete(img_id: int):
    """
    Delete a single image row by ID. If the file exists on disk,
    attempt to remove it after DB commit (best effort).
    """
    r = require_admin()
    if r:
        return r

    conn = get_db()
    try:
        row = conn.execute("""
            SELECT id, COALESCE(filename, file_name) AS filename
              FROM house_images
             WHERE id=?
        """, (img_id,)).fetchone()

        if not row:
            flash("Image not found.", "error")
            return redirect(url_for("admin.admin_images"))

        fname = row["filename"]

        try:
            conn.execute("DELETE FROM house_images WHERE id=?", (img_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            flash("Could not delete image from the database.", "error")
            return redirect(url_for("admin.admin_images"))
    finally:
        conn.close()

    # Best-effort file removal after DB success
    try:
        fp = file_abs_path(fname)
        if os.path.exists(fp):
            os.remove(fp)
    except Exception:
        pass

    flash(f"Image {img_id} deleted.", "ok")
    return redirect(url_for("admin.admin_images"))


@bp.route("/images/cleanup-broken", methods=["POST"])
def admin_images_cleanup_broken():
    """
    Bulk delete: removes all rows whose files are missing on disk.
    DB-first; file removal is skipped (they're already missing).
    """
    r = require_admin()
    if r:
        return r

    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, COALESCE(filename, file_name) AS filename
              FROM house_images
        """).fetchall()

        to_delete = []
        for r_ in rows:
            if not os.path.exists(file_abs_path(r_["filename"])):
                to_delete.append(r_["id"])

        if not to_delete:
            flash("No broken images to clean up.", "ok")
            return redirect(url_for("admin.admin_images", broken=1))

        try:
            conn.executemany("DELETE FROM house_images WHERE id=?", [(i,) for i in to_delete])
            conn.commit()
        except Exception:
            conn.rollback()
            flash("Could not clean up broken images.", "error")
            return redirect(url_for("admin.admin_images", broken=1))

        flash(f"Deleted {len(to_delete)} broken image rows.", "ok")
        return redirect(url_for("admin.admin_images", broken=1))
    finally:
        conn.close()
