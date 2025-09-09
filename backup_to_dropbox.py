# backup_to_dropbox.py
from __future__ import annotations

import os, io, time, json, zipfile
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

import dropbox
from dropbox.files import WriteMode

# --- Config from env ---
DROPBOX_ACCESS_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN", "")
# Root folder in Dropbox (you can change to e.g. "/Backups/SP")
DROPBOX_BACKUP_ROOT = os.getenv("DROPBOX_BACKUP_ROOT", "/student-palace/backups")
# Also upload a .zip alongside the extracted files
UPLOAD_ZIP_SNAPSHOT = os.getenv("UPLOAD_ZIP_SNAPSHOT", "1") not in ("0", "false", "False")


def _now_utc_slug() -> Tuple[str, str]:
    # Folder and filename-safe UTC stamps
    folder_stamp = time.strftime("%Y-%m-%d_%H-%M-%SZ", time.gmtime())
    file_stamp = time.strftime("%Y%m%d-%H%M%SZ", time.gmtime())
    return folder_stamp, file_stamp


def _add_dir_to_zip(zf: zipfile.ZipFile, base: Path, arc_prefix: str) -> dict:
    total_files = 0
    total_bytes = 0
    if not base.exists():
        return {"files": 0, "bytes": 0}
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            if name.endswith((".pyc", ".pyo", ".DS_Store")):
                continue
            abs_path = Path(root) / name
            try:
                rel = abs_path.relative_to(base)
            except Exception:
                rel = Path(name)
            arcname = str(Path(arc_prefix) / rel)
            try:
                zf.write(abs_path, arcname)
                st = abs_path.stat()
                total_files += 1
                total_bytes += int(st.st_size)
            except Exception:
                pass
    return {"files": total_files, "bytes": total_bytes}


def _dbx_client() -> dropbox.Dropbox:
    if not DROPBOX_ACCESS_TOKEN:
        raise RuntimeError("DROPBOX_ACCESS_TOKEN is not set")
    return dropbox.Dropbox(DROPBOX_ACCESS_TOKEN, timeout=300)


def _dbx_put_bytes(dbx: dropbox.Dropbox, path: str, data: bytes) -> None:
    # Ensure leading slash
    if not path.startswith("/"):
        path = "/" + path
    dbx.files_upload(data, path, mode=WriteMode("overwrite"))


def _dbx_put_file(dbx: dropbox.Dropbox, local_path: Path, dropbox_path: str) -> None:
    if not dropbox_path.startswith("/"):
        dropbox_path = "/" + dropbox_path
    size = local_path.stat().st_size
    # Simple upload is fine for typical sizes; chunk if very large (>140MB)
    if size < 140 * 1024 * 1024:
        with local_path.open("rb") as f:
            dbx.files_upload(f.read(), dropbox_path, mode=WriteMode("overwrite"))
    else:
        # Chunked upload for large files
        CHUNK = 8 * 1024 * 1024
        with local_path.open("rb") as f:
            session = dbx.files_upload_session_start(f.read(CHUNK))
            cursor = dropbox.files.UploadSessionCursor(session_id=session.session_id, offset=f.tell())
            commit = dropbox.files.CommitInfo(path=dropbox_path, mode=WriteMode("overwrite"))
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                if len(chunk) < CHUNK:
                    dbx.files_upload_session_finish(chunk, cursor, commit)
                    break
                dbx.files_upload_session_append_v2(chunk, cursor)
                cursor.offset += len(chunk)


def run_backup() -> str:
    """
    Builds a full backup and uploads *extracted files* into Dropbox:
      /<ROOT>/<YYYY-MM-DD_HH-MM-SSZ>/
        database/student_palace.db
        site-files/static/uploads/**/*
        manifest.json
      (+ optional ZIP snapshot in same folder)

    Returns the Dropbox folder path created.
    """
    # Lazy imports to avoid circulars
    from db import DB_PATH
    project_root = Path(__file__).resolve().parent
    # admin/.. -> project root
    # Walk upward until we find 'static'; conservative:
    for _ in range(4):
        if (project_root / "static").exists():
            break
        project_root = project_root.parent

    uploads_dir = project_root / "static" / "uploads"
    db_path = Path(DB_PATH)

    # Build manifest and (optionally) in-memory ZIP
    ts_folder, ts_file = _now_utc_slug()

    db_info = {"exists": db_path.exists(), "bytes": int(db_path.stat().st_size) if db_path.exists() else 0}
    buf = io.BytesIO()
    uploads_info = {"files": 0, "bytes": 0}

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        if db_path.exists():
            zf.write(db_path, arcname="database/student_palace.db")
        uploads_info = _add_dir_to_zip(zf, uploads_dir, "site-files/static/uploads")
        manifest: Dict[str, Any] = {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "notes": "Student Palace scheduled backup (extracted + zip).",
            "database": {"path": str(db_path), **db_info},
            "uploads": {"path": str(uploads_dir), **uploads_info},
            "versions": {"python_time": time.time()},
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

    buf.seek(0)

    # Upload to Dropbox
    dbx = _dbx_client()
    base = f"{DROPBOX_BACKUP_ROOT.rstrip('/')}/{ts_folder}"

    # 1) Upload DB (extracted)
    if db_path.exists():
        _dbx_put_file(dbx, db_path, f"{base}/database/student_palace.db")

    # 2) Upload uploads folder (extracted)
    if uploads_dir.exists():
        for root, dirs, files in os.walk(uploads_dir):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for name in files:
                if name.endswith((".pyc", ".pyo", ".DS_Store")):
                    continue
                src = Path(root) / name
                rel = src.relative_to(uploads_dir)
                drop_path = f"{base}/site-files/static/uploads/{rel.as_posix()}"
                _dbx_put_file(dbx, src, drop_path)

    # 3) Upload manifest.json (extracted copy, too)
    manifest_bytes = json.dumps({
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "database": {"path": str(db_path), **db_info},
        "uploads": {"path": str(uploads_dir), **uploads_info},
        "note": "This is a duplicate of the manifest stored inside the .zip"
    }, indent=2, sort_keys=True).encode("utf-8")
    _dbx_put_bytes(dbx, f"{base}/manifest.json", manifest_bytes)

    # 4) (Optional) upload the ZIP snapshot as well
    if UPLOAD_ZIP_SNAPSHOT:
        zip_name = f"student-palace-backup-{ts_file}.zip"
        _dbx_put_bytes(dbx, f"{base}/{zip_name}", buf.getvalue())

    return "/" + base.lstrip("/")
