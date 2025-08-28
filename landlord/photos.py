# landlord/photos.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from datetime import datetime as dt

from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none

# use the shared landlord blueprint defined in landlord/__init__.py
from . import bp

# image helpers (already in your repo)
from image_helpers import (
    accept_upload, select_images, set_primary, delete_image,
    MAX_FILES_PER_HOUSE,
    assert_house_images_schema, ensure_upload_dir
)


@bp.route("/landlord/houses/<int:hid>/photos", methods=["GET", "POST"])
def house_photos(hid: int):
    """
    GET  -> show existing photos + upload form
    POST -> accept a SINGLE file upload (safe first step)
    """
    # login/ownership checks
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()

    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    # guard: make sure DB schema is what we expect before doing anything
    try:
        assert_house_images_schema(conn)
    except Exception as e:
        conn.close()
        flash(f"Photo feature is not available: {e}", "error")
        return render_template(
            "house_photos.html",
            house=house,
            images=[],
            max_images=MAX_FILES_PER_HOUSE,
        )

    # handle single-file upload (first, safe step)
    if request.method == "POST":
        f = request.files.get("photo")
        if not f or not getattr(f, "filename", ""):
            images = select_images(conn, hid)
            conn.close()
            flash("Please choose a photo to upload.", "error")
            return render_template(
                "house_photos.html",
                house=house,
                images=images,
                max_images=MAX_FILES_PER_HOUSE,
            )

        ok, msg = accept_upload(conn, hid, f, enforce_limit=True)
        try:
            if ok:
                conn.commit()
                flash("Photo uploaded.", "ok")
            else:
                conn.rollback()
                flash(msg, "error")
        except Exception:
            # if commit/rollback itself fails, just close and show a friendly error
            flash("Could not finalize the upload.", "error")
        finally:
            conn.close()

        return redirect(url_for("landlord.house_photos", hid=hid))

    # GET: list images
    images = select_images(conn, hid)
    conn.close()
    return render_template(
        "house_photos.html",
        house=house,
        images=images,
        max_images=MAX_FILES_PER_HOUSE,
    )


@bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/primary", methods=["POST"])
def house_photos_primary(hid: int, img_id: int):
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    try:
        assert_house_images_schema(conn)
        set_primary(conn, hid, img_id)
        conn.commit()
        flash("Primary photo set.", "ok")
    except Exception as e:
        conn.rollback()
        flash("Could not set primary photo.", "error")
    finally:
        conn.close()

    return redirect(url_for("landlord.house_photos", hid=hid))


@bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/delete", methods=["POST"])
def house_photos_delete(hid: int, img_id: int):
    r = require_landlord()
    if r:
        return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        flash("House not found.", "error")
        return redirect(url_for("landlord.landlord_houses"))

    try:
        assert_house_images_schema(conn)
        fname = delete_image(conn, hid, img_id)
        if not fname:
            conn.rollback()
            conn.close()
            flash("Photo not found.", "error")
            return redirect(url_for("landlord.house_photos", hid=hid))

        conn.commit()  # DB first
        conn.close()

        # after DB success, try to remove the file (best effort)
        from image_helpers import file_abs_path
        import os
        try:
            os.remove(file_abs_path(fname))
        except Exception:
            pass

        flash("Photo deleted.", "ok")
    except Exception:
        conn.rollback()
        conn.close()
        flash("Could not delete photo.", "error")

    return redirect(url_for("landlord.house_photos", hid=hid))
