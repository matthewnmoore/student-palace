# landlord/photos.py
from __future__ import annotations

from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none

# Shared landlord blueprint (declared in landlord/__init__.py)
from . import bp

# Image helpers (your vetted module)
from image_helpers import (
    accept_upload,
    select_images,
    set_primary,
    delete_image,
    assert_house_images_schema,
    MAX_FILES_PER_HOUSE,
)


@bp.route("/landlord/houses/<int:hid>/photos", methods=["GET", "POST"])
def house_photos(hid: int):
    """
    GET  -> Show existing photos + single-file upload form.
    POST -> Accept ONE file upload (keeps first step simple & safe).
    """
    # Auth + ownership
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

    # Guard: ensure DB schema matches our documented requirements
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

    # POST: single-file upload
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
    # Auth + ownership
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
    except Exception:
        conn.rollback()
        flash("Could not set primary photo.", "error")
    finally:
        conn.close()

    return redirect(url_for("landlord.house_photos", hid=hid))


@bp.route("/landlord/houses/<int:hid>/photos/<int:img_id>/delete", methods=["POST"])
def house_photos_delete(hid: int, img_id: int):
    # Auth + ownership
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

        # Commit DB deletion first
        conn.commit()
        conn.close()

        # Best-effort: remove the file from disk
        import os
        from image_helpers import file_abs_path
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
