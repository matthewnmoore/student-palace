from __future__ import annotations

import os
import time
import logging
from datetime import datetime as dt
from typing import Optional

from flask import render_template, request, redirect, url_for, flash, send_from_directory
from db import get_db
from utils import current_landlord_id, require_landlord, owned_house_or_none
from . import bp

logger = logging.getLogger("student_palace.epc")

# Storage: under /static/uploads/houses/epc/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_ROOT = os.path.join(PROJECT_ROOT, "static")
EPC_DIR = os.path.join(STATIC_ROOT, "uploads", "houses", "epc")  # served at /static/uploads/houses/epc

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIME = "application/pdf"

def _ensure_dir() -> None:
    os.makedirs(EPC_DIR, exist_ok=True)

def _static_rel_path(filename: str) -> str:
    # store WITHOUT a leading slash; render with url_for('static', filename=...)
    return f"uploads/houses/epc/{filename}"

def _file_abs_path(filename: str) -> str:
    return os.path.join(EPC_DIR, filename)

def _rand_token(n: int = 6) -> str:
    import secrets
    return secrets.token_hex(max(3, n // 2))

def _read_limited(file_storage) -> Optional[bytes]:
    data = file_storage.read(MAX_PDF_BYTES + 1)
    file_storage.stream.seek(0)
    return data if data else None

def _current_epc_row(conn, hid: int):
    return conn.execute("""
        SELECT id, house_id, doc_type, file_name, file_path, bytes, created_at, is_current
          FROM house_documents
         WHERE house_id=? AND doc_type='epc' AND is_current=1
         ORDER BY id DESC
         LIMIT 1
    """, (hid,)).fetchone()

def _list_epc_history(conn, hid: int):
    return conn.execute("""
        SELECT id, house_id, doc_type, file_name, file_path, bytes, created_at, is_current
          FROM house_documents
         WHERE house_id=? AND doc_type='epc'
         ORDER BY is_current DESC, id DESC
    """, (hid,)).fetchall()

@bp.route("/landlord/houses/<int:hid>/epc", methods=["GET", "POST"])
def house_epc(hid: int):
    """
    GET  -> show existing EPC (current + history) and upload form
    POST -> accept ONE PDF; make it the current EPC; keep prior as history (non-current)
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

    if request.method == "POST":
        file = request.files.get("epc_pdf")
        if not file or not getattr(file, "filename", "").strip():
            rows = _list_epc_history(conn, hid)
            conn.close()
            flash("Please choose a PDF file to upload.", "error")
            return render_template("house_epc.html", house=house, docs=rows)

        mimetype = (getattr(file, "mimetype", "") or "").lower()
        if mimetype != ALLOWED_MIME:
            rows = _list_epc_history(conn, hid)
            conn.close()
            flash("Only PDF files are allowed.", "error")
            return render_template("house_epc.html", house=house, docs=rows)

        data = _read_limited(file)
        if not data:
            rows = _list_epc_history(conn, hid)
            conn.close()
            flash("Could not read the file.", "error")
            return render_template("house_epc.html", house=house, docs=rows)
        if len(data) > MAX_PDF_BYTES:
            rows = _list_epc_history(conn, hid)
            conn.close()
            mb = f"{MAX_PDF_BYTES/1024/1024:.0f}"
            flash(f"PDF is larger than {mb} MB.", "error")
            return render_template("house_epc.html", house=house, docs=rows)

        # Save to disk
        _ensure_dir()
        ts = dt.utcnow().strftime("%Y%m%d%H%M%S")
        fname = f"house{hid}_epc_{ts}_{_rand_token(8)}.pdf"
        abs_path = _file_abs_path(fname)
        try:
            with open(abs_path, "wb") as fh:
                fh.write(data)
            size_bytes = os.path.getsize(abs_path)
        except Exception:
            logger.exception("[EPC] FS write failed")
            rows = _list_epc_history(conn, hid)
            conn.close()
            flash("Server storage is not available.", "error")
            return render_template("house_epc.html", house=house, docs=rows)

        # DB: mark previous as non-current, insert new as current
        try:
            conn.execute("""
                UPDATE house_documents
                   SET is_current=0
                 WHERE house_id=? AND doc_type='epc' AND is_current=1
            """, (hid,))
            conn.execute("""
                INSERT INTO house_documents(house_id, doc_type, file_name, file_path, bytes, created_at, is_current)
                VALUES (?,?,?,?,?,?,1)
            """, (
                hid, "epc", fname, _static_rel_path(fname), size_bytes, dt.utcnow().isoformat()
            ))
            conn.commit()
            flash("EPC PDF uploaded.", "ok")
        except Exception:
            conn.rollback()
            try:
                os.remove(abs_path)
            except Exception:
                pass
            conn.close()
            flash("Could not record the EPC in the database.", "error")
            return redirect(url_for("landlord.house_epc", hid=hid))

        rows = _list_epc_history(conn, hid)
        conn.close()
        return render_template("house_epc.html", house=house, docs=rows)

    # GET
    rows = _list_epc_history(conn, hid)
    conn.close()
    return render_template("house_epc.html", house=house, docs=rows)

@bp.route("/landlord/houses/<int:hid>/epc/<int:doc_id>/delete", methods=["POST"])
def house_epc_delete(hid: int, doc_id: int):
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

    row = conn.execute("""
        SELECT id, file_name, is_current
          FROM house_documents
         WHERE id=? AND house_id=? AND doc_type='epc'
    """, (doc_id, hid)).fetchone()
    if not row:
        conn.close()
        flash("EPC PDF not found.", "error")
        return redirect(url_for("landlord.house_epc", hid=hid))

    # Prevent deleting the current EPC if it's the only one
    current_count = conn.execute("""
        SELECT COUNT(*) AS c
          FROM house_documents
         WHERE house_id=? AND doc_type='epc' AND is_current=1
    """, (hid,)).fetchone()
    only_one_current = int(current_count["c"]) == 1 and int(row["is_current"]) == 1

    # If trying to delete the last current, block
    if only_one_current:
        # Check if there is any other history doc to promote; if none, block delete
        others = conn.execute("""
            SELECT id FROM house_documents WHERE house_id=? AND doc_type='epc' AND id<>?
        """, (hid, row["id"])).fetchone()
        if not others:
            conn.close()
            flash("Cannot delete the only current EPC. Upload a new one first.", "error")
            return redirect(url_for("landlord.house_epc", hid=hid))

    fname = row["file_name"]
    try:
        conn.execute("DELETE FROM house_documents WHERE id=? AND house_id=? AND doc_type='epc'", (doc_id, hid))
        # If we deleted the current one but others exist, promote the most recent to current
        if int(row["is_current"]) == 1:
            promote = conn.execute("""
                SELECT id FROM house_documents
                 WHERE house_id=? AND doc_type='epc'
                 ORDER BY id DESC LIMIT 1
            """, (hid,)).fetchone()
            if promote:
                conn.execute("UPDATE house_documents SET is_current=1 WHERE id=?", (promote["id"],))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        flash("Could not delete EPC PDF.", "error")
        return redirect(url_for("landlord.house_epc", hid=hid))

    conn.close()
    # Best-effort remove file from disk
    try:
        os.remove(_file_abs_path(fname))
    except Exception:
        pass

    flash("EPC PDF deleted.", "ok")
    return redirect(url_for("landlord.house_epc", hid=hid))
