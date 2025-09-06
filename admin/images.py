# admin/images.py
from __future__ import annotations

import os, io, sqlite3
from urllib.parse import urlencode
from flask import render_template, request, redirect, url_for, flash
from PIL import Image

# Prefer the existing import your file used, but keep a safe fallback
try:
    from models import get_db as _models_get_db  # legacy path in some parts of the app
except Exception:
    _models_get_db = None

try:
    from db import get_db as _db_get_db
except Exception:
    _db_get_db = None

def get_db():
    if _models_get_db is not None:
        return _models_get_db()
    if _db_get_db is not None:
        return _db_get_db()
    raise RuntimeError("No get_db() available")

from image_helpers import (
    file_abs_path as house_abs,
    process_image as process_any_image,   # open → auto-orient → resize(1600) → watermark
    save_jpeg as save_any_jpeg,
)
from image_helpers_rooms import file_abs_path_room as room_abs

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
            exists = os.path.exists(house_abs(fname))
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

        # Build pagination URLs in Python
        args = request.args.to_dict(flat=True)

        prev_url = None
        if page > 1:
            prev_params = dict(args)
            prev_params["page"] = page - 1
            prev_url = url_for("admin.admin_images") + "?" + urlencode(prev_params)

        next_url = None
        if len(items) == limit:
            next_params = dict(args)
            next_params["page"] = page + 1
            next_url = url_for("admin.admin_images") + "?" + urlencode(next_params)

        return render_template(
            "admin_images.html",
            items=items,
            page=page,
            limit=limit,
            total=total,
            broken_only=broken_only,
            prev_url=prev_url,
            next_url=next_url,
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
        fp = house_abs(fname)
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
            if not os.path.exists(house_abs(r_["filename"])):
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


# ----------------------------
# Re-watermark / Reprocess ops
# ----------------------------

def _with_row_factory(conn):
    try:
        conn.row_factory = sqlite3.Row
    except Exception:
        pass
    return conn

@bp.post("/images/rewatermark-all")
def admin_images_rewatermark_all():
    """Re-watermark & re-save all existing HOUSE images on disk (best effort)."""
    r = require_admin()
    if r:
        return r

    conn = get_db()
    conn = _with_row_factory(conn)

    try:
        rows = conn.execute("""
            SELECT id, COALESCE(filename, file_name) AS filename
              FROM house_images
             ORDER BY id ASC
        """).fetchall()
    finally:
        conn.close()

    updated = 0
    missing = 0
    failed  = 0

    for row in rows:
        fname = row["filename"]
        ap = house_abs(fname)
        if not os.path.exists(ap):
            missing += 1
            continue
        try:
            # Read existing JPEG to bytes → run our standard pipeline → overwrite
            with Image.open(ap) as im_src:
                buf = io.BytesIO()
                im_src.save(buf, format="JPEG")
                data = buf.getvalue()

            im = process_any_image(data)
            save_any_jpeg(im, ap)
            updated += 1
        except Exception:
            failed += 1

    flash(
        f"House photos reprocessed. updated={updated}, missing={missing}, failed={failed}",
        "ok" if failed == 0 else "error"
    )
    return redirect(url_for("admin.admin_images"))

@bp.post("/images/rewatermark-rooms")
def admin_images_rewatermark_rooms():
    """Re-watermark & re-save all existing ROOM images on disk (best effort)."""
    r = require_admin()
    if r:
        return r

    conn = get_db()
    conn = _with_row_factory(conn)

    try:
        rows = conn.execute("""
            SELECT id, COALESCE(filename, file_name) AS filename
              FROM room_images
             ORDER BY id ASC
        """).fetchall()
    finally:
        conn.close()

    updated = 0
    missing = 0
    failed  = 0

    for row in rows:
        fname = row["filename"]
        ap = room_abs(fname)
        if not os.path.exists(ap):
            missing += 1
            continue
        try:
            with Image.open(ap) as im_src:
                buf = io.BytesIO()
                im_src.save(buf, format="JPEG")
                data = buf.getvalue()

            im = process_any_image(data)
            save_any_jpeg(im, ap)
            updated += 1
        except Exception:
            failed += 1

    flash(
        f"Room photos reprocessed. updated={updated}, missing={missing}, failed={failed}",
        "ok" if failed == 0 else "error"
    )
    return redirect(url_for("admin.admin_images"))
