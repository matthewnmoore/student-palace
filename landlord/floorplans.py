# landlord/floorplans.py
from __future__ import annotations

# --- Pillow compatibility shim (keeps requirements and helpers unchanged) ---
# Some Pillow builds removed ImageDraw.textsize in favor of textbbox.
# We reintroduce textsize at runtime so downstream code continues to work.
try:
    from PIL import ImageDraw, __version__ as _PIL_VERSION
    if not hasattr(ImageDraw.ImageDraw, "textsize"):
        def _compat_textsize(self, text, font=None, *args, **kwargs):
            bbox = self.textbbox((0, 0), text, font=font, *args, **kwargs)
            return (bbox[2] - bbox[0], bbox[3] - bbox[1])
        ImageDraw.ImageDraw.textsize = _compat_textsize  # monkey-patch
    # Optional: one-time log for visibility
    try:
        import logging as _logging
        _logging.getLogger("student_palace.floorplans").info(
            f"[PIL] version={_PIL_VERSION} textsize={'present' if hasattr(ImageDraw.ImageDraw, 'textsize') else 'shimmed'}"
        )
    except Exception:
        pass
except Exception:
    # If PIL import fails here, your helper will raise its own error later.
    pass
# ---------------------------------------------------------------------------

import time, logging, os
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none
from . import bp

from image_helpers_floorplans import (
    accept_upload_plan, select_plans, set_primary_plan, delete_plan,
    MAX_FILES_PER_HOUSE_PLANS, assert_house_floorplans_schema,
    file_abs_path_plan
)

logger = logging.getLogger("student_palace.floorplans")

@bp.route("/landlord/houses/<int:hid>/floor-plans", methods=["GET", "POST"])
def house_floorplans(hid: int):
    """
    GET  -> show existing floor plans + upload form
    POST -> accept MULTIPLE file uploads (safe batch)
    """
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
        assert_house_floorplans_schema(conn)
    except Exception as e:
        conn.close()
        flash(f"Floor plans feature is not available: {e}", "error")
        return render_template(
            "house_floorplans.html",
            house=house,
            plans=[],
            max_plans=MAX_FILES_PER_HOUSE_PLANS,
        )

    if request.method == "POST":
        batch_start = time.perf_counter()

        files = request.files.getlist("plans")
        files = [f for f in files if getattr(f, "filename", "").strip()]

        if not files:
            plans = select_plans(conn, hid)
            conn.close()
            flash("Please choose at least one floor plan to upload.", "error")
            return render_template(
                "house_floorplans.html",
                house=house,
                plans=plans,
                max_plans=MAX_FILES_PER_HOUSE_PLANS,
            )

        existing = len(select_plans(conn, hid))
        remaining = max(0, MAX_FILES_PER_HOUSE_PLANS - existing)
        if remaining <= 0:
            conn.close()
            flash(f"House already has {MAX_FILES_PER_HOUSE_PLANS} floor plans.", "error")
            return redirect(url_for("landlord.house_floorplans", hid=hid))

        to_process = files[:remaining]

        successes = 0
        errors = []
        for f in to_process:
            ok, msg = accept_upload_plan(conn, hid, f, enforce_limit=False)
            if ok:
                successes += 1
            else:
                errors.append(f"{getattr(f, 'filename', 'file')}: {msg}")

        try:
            if successes:
                conn.commit()
            else:
                conn.rollback()
        except Exception:
            flash("Could not finalize the upload.", "error")
            conn.close()
            return redirect(url_for("landlord.house_floorplans", hid=hid))

        elapsed = time.perf_counter() - batch_start
        logger.info(
            f"[FLOORPLANS-BATCH] house={hid} tried={len(files)} processed={len(to_process)} "
            f"success={successes} errors={len(errors)} elapsed={elapsed:.2f}s"
        )

        skipped_due_to_limit = len(files) - len(to_process)
        parts = []
        if successes:
            parts.append(f"Uploaded {successes} file{'s' if successes != 1 else ''}.")
        if errors:
            parts.append(f"Skipped {len(errors)} due to errors.")
        if skipped_due_to_limit > 0:
            parts.append(f"{skipped_due_to_limit} not processed (house limit {MAX_FILES_PER_HOUSE_PLANS}).")

        if successes:
            flash(" ".join(parts), "ok")
        else:
            detail = " ".join(parts) if parts else "Upload failed."
            flash(detail, "error")
            for e in errors:
                flash(e, "error")

        conn.close()
        return redirect(url_for("landlord.house_floorplans", hid=hid))

    # GET
    plans = select_plans(conn, hid)
    conn.close()
    return render_template(
        "house_floorplans.html",
        house=house,
        plans=plans,
        max_plans=MAX_FILES_PER_HOUSE_PLANS,
    )

@bp.route("/landlord/houses/<int:hid>/floor-plans/<int:pid>/primary", methods=["POST"])
def house_floorplans_primary(hid: int, pid: int):
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
        assert_house_floorplans_schema(conn)
        set_primary_plan(conn, hid, pid)
        conn.commit()
        flash("Primary floor plan set.", "ok")
    except Exception:
        conn.rollback()
        flash("Could not set primary floor plan.", "error")
    finally:
        conn.close()

    return redirect(url_for("landlord.house_floorplans", hid=hid))

@bp.route("/landlord/houses/<int:hid>/floor-plans/<int:pid>/delete", methods=["POST"])
def house_floorplans_delete(hid: int, pid: int):
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
        assert_house_floorplans_schema(conn)
        fname = delete_plan(conn, hid, pid)
        if not fname:
            conn.rollback()
            conn.close()
            flash("Floor plan not found.", "error")
            return redirect(url_for("landlord.house_floorplans", hid=hid))

        conn.commit()
        conn.close()

        # Best-effort file deletion after DB success
        try:
            os.remove(file_abs_path_plan(fname))
        except Exception:
            pass

        flash("Floor plan deleted.", "ok")
    except Exception:
        conn.rollback()
        conn.close()
        flash("Could not delete floor plan.", "error")

    return redirect(url_for("landlord.house_floorplans", hid=hid))

@bp.route("/landlord/houses/<int:hid>/floor-plans/debug")
def house_floorplans_debug(hid: int):
    r = require_landlord()
    if r: return r
    lid = current_landlord_id()
    conn = get_db()
    house = owned_house_or_none(conn, hid, lid)
    if not house:
        conn.close()
        return {"error":"house not found"}, 404

    rows = conn.execute("""
      SELECT id,
             COALESCE(filename, file_name) AS filename,
             file_path, width, height, bytes, is_primary, sort_order, created_at
        FROM house_floorplans
       WHERE house_id=?
       ORDER BY is_primary DESC, sort_order ASC, id ASC
    """, (hid,)).fetchall()
    conn.close()

    out = []
    for r in rows:
        fname = r["filename"]
        out.append({
            "id": r["id"],
            "filename": fname,
            "file_path": r["file_path"],
            "exists_on_disk": os.path.exists(file_abs_path_plan(fname)),
            "is_primary": int(r["is_primary"]) == 1,
            "size_wxh": f'{r["width"]}x{r["height"]}',
            "bytes": r["bytes"],
        })
    return {"house_id": hid, "items": out}, 200, {"Content-Type":"application/json"}
