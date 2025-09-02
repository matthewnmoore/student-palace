from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils import current_landlord_id, require_landlord
from . import bp
import os
from pathlib import Path
from PIL import Image
from werkzeug.utils import secure_filename
import glob

UPLOAD_ROOT = "static/uploads/landlords"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def _purge_previous(dir_path: Path, stem: str) -> None:
    """
    Remove any existing files for this asset (e.g., logo.* or photo.*) in the landlord folder.
    This keeps only the newest upload.
    """
    try:
        for p in dir_path.glob(f"{stem}.*"):
            try:
                p.unlink()
            except Exception:
                pass
    except Exception:
        pass

def _save_image(file_storage, dest_path: Path, size=(512, 512), quality=85):
    """
    Save an uploaded image with resizing and compression so it stays small (~150–250 KB).
    Always re-encodes as JPEG for consistency.
    Returns the final Path written.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    # Ensure .jpg extension and purge any older variants first
    final_path = dest_path.with_suffix(".jpg")
    _purge_previous(final_path.parent, final_path.stem)

    try:
        img = Image.open(file_storage)
        img = img.convert("RGB")  # ensure safe for JPEG
        img.thumbnail(size)
        img.save(final_path, "JPEG", quality=quality, optimize=True)
        return final_path
    except Exception as e:
        print("[ERROR] processing image:", e)
        # Fallback raw save (still enforce .jpg name)
        try:
            file_storage.save(final_path)
        except Exception:
            pass
        return final_path

@bp.route("/landlord/profile", methods=["GET","POST"])
def landlord_profile():
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    prof = conn.execute(
        "SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)
    ).fetchone()
    if not prof:
        conn.execute(
            "INSERT INTO landlord_profiles(landlord_id, display_name) VALUES (?,?)",
            (lid, "")
        )
        conn.commit()
        prof = conn.execute(
            "SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)
        ).fetchone()

    if request.method == "POST":
        action = request.form.get("action") or "save"

        # --- Upload logo ---
        if action == "upload_logo":
            f = request.files.get("logo")
            if f and _allowed_file(f.filename):
                fn = secure_filename("logo.jpg")
                dest = Path(UPLOAD_ROOT) / str(lid) / fn
                saved_path = _save_image(f, dest)
                rel_path = str(saved_path.relative_to("static"))
                conn.execute("UPDATE landlord_profiles SET logo_path=? WHERE landlord_id=?", (rel_path, lid))
                conn.commit()
                flash("Logo uploaded.", "ok")
            else:
                flash("Invalid logo file.", "error")
            conn.close()
            return redirect(url_for("landlord.landlord_profile"))

        # --- Remove logo ---
        if action == "remove_logo":
            old = prof["logo_path"] if prof and "logo_path" in prof.keys() else None
            if old:
                try:
                    (Path("static") / old).unlink(missing_ok=True)
                except Exception:
                    pass
            # Also purge any lingering legacy logo.* files
            _purge_previous(Path(UPLOAD_ROOT) / str(lid), "logo")
            conn.execute("UPDATE landlord_profiles SET logo_path=NULL WHERE landlord_id=?", (lid,))
            conn.commit()
            flash("Logo removed.", "ok")
            conn.close()
            return redirect(url_for("landlord.landlord_profile"))

        # --- Upload photo ---
        if action == "upload_photo":
            f = request.files.get("photo")
            if f and _allowed_file(f.filename):
                fn = secure_filename("photo.jpg")
                dest = Path(UPLOAD_ROOT) / str(lid) / fn
                saved_path = _save_image(f, dest)
                rel_path = str(saved_path.relative_to("static"))
                conn.execute("UPDATE landlord_profiles SET photo_path=? WHERE landlord_id=?", (rel_path, lid))
                conn.commit()
                flash("Profile photo uploaded.", "ok")
            else:
                flash("Invalid photo file.", "error")
            conn.close()
            return redirect(url_for("landlord.landlord_profile"))

        # --- Remove photo ---
        if action == "remove_photo":
            old = prof["photo_path"] if prof and "photo_path" in prof.keys() else None
            if old:
                try:
                    (Path("static") / old).unlink(missing_ok=True)
                except Exception:
                    pass
            # Also purge any lingering legacy photo.* files
            _purge_previous(Path(UPLOAD_ROOT) / str(lid), "photo")
            conn.execute("UPDATE landlord_profiles SET photo_path=NULL WHERE landlord_id=?", (lid,))
            conn.commit()
            flash("Profile photo removed.", "ok")
            conn.close()
            return redirect(url_for("landlord.landlord_profile"))

        # --- Save text fields (default action) ---
        try:
            from utils import slugify
            display_name = (request.form.get("display_name") or "").strip()
            phone = (request.form.get("phone") or "").strip()
            website = (request.form.get("website") or "").strip()
            bio = (request.form.get("bio") or "").strip()
            role = (request.form.get("role") or "").strip().lower()
            if role not in ("owner", "agent"):
                role = (prof["role"] if prof and "role" in prof.keys() else "owner")

            slug = prof["public_slug"]
            if not slug and display_name:
                base = slugify(display_name)
                candidate = base
                i = 2
                while conn.execute(
                    "SELECT 1 FROM landlord_profiles WHERE public_slug=?", (candidate,)
                ).fetchone():
                    candidate = f"{base}-{i}"
                    i += 1
                slug = candidate

            conn.execute("""
                UPDATE landlord_profiles
                   SET display_name=?, phone=?, website=?, bio=?, role=?,
                       public_slug=COALESCE(?, public_slug)
                 WHERE landlord_id=?
            """, (display_name, phone, website, bio, role, slug, lid))
            conn.commit()
            flash("Profile saved.", "ok")
        except Exception as e:
            print("[ERROR] landlord_profile POST:", e)
            flash("Could not save profile.", "error")
        conn.close()
        return redirect(url_for("landlord.landlord_profile"))

    conn.close()
    return render_template("landlord_profile_edit.html", profile=prof)

# Public profile views
@bp.route("/l/<slug>")
def landlord_public_by_slug(slug):
    conn = get_db()
    prof = conn.execute(
        "SELECT * FROM landlord_profiles WHERE public_slug=?", (slug,)
    ).fetchone()
    if not prof:
        conn.close()
        return render_template("landlord_profile_public.html", profile=None), 404
    conn.execute(
        "UPDATE landlord_profiles SET profile_views=profile_views+1 WHERE landlord_id=?",
        (prof["landlord_id"],)
    )
    conn.commit()
    ll = conn.execute(
        "SELECT email FROM landlords WHERE id=?", (prof["landlord_id"],)
    ).fetchone()
    conn.close()
    return render_template(
        "landlord_profile_public.html",
        profile=prof,
        contact_email=ll["email"] if ll else ""
    )

@bp.route("/l/id/<int:lid>")
def landlord_public_by_id(lid):
    conn = get_db()
    prof = conn.execute(
        "SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)
    ).fetchone()
    if not prof:
        conn.close()
        return render_template("landlord_profile_public.html", profile=None), 404
    conn.execute(
        "UPDATE landlord_profiles SET profile_views=profile_views+1 WHERE landlord_id=?",
        (lid,)
    )
    conn.commit()
    ll = conn.execute(
        "SELECT email FROM landlords WHERE id=?", (lid,)
    ).fetchone()
    conn.close()
    return render_template(
        "landlord_profile_public.html",
        profile=prof,
        contact_email=ll["email"] if ll else ""
    )

