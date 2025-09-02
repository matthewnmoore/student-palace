from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils import current_landlord_id, require_landlord
from . import bp

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
            prof = conn.execute(
                "SELECT * FROM landlord_profiles WHERE landlord_id=?", (lid,)
            ).fetchone()
            conn.close()
            flash("Profile saved.", "ok")
            return redirect(url_for("landlord.landlord_profile"))
        except Exception as e:
            conn.close()
            print("[ERROR] landlord_profile POST:", e)
            flash("Could not save profile.", "error")
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
