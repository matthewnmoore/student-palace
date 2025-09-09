# backup_to_dropbox.py
from __future__ import annotations

import os, io, time, json, zipfile
from pathlib import Path
from typing import Dict, Any, Tuple

import dropbox
from dropbox.files import WriteMode, UploadSessionCursor, CommitInfo
from dropbox.exceptions import ApiError, AuthError

# ==== Config (env) ====
# Long-term (recommended):
DBX_APP_KEY = os.getenv("DROPBOX_APP_KEY", "")
DBX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET", "")
DBX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN", "")

# Fallback (short-lived or manually rotated):
DBX_ACCESS_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN", "")

# Where to put backups in Dropbox:
DROPBOX_BACKUP_ROOT = os.getenv("DROPBOX_BACKUP_ROOT", "/student-palace/backups")

# Also upload a single ZIP file next to the extracted files:
UPLOAD_ZIP_SNAPSHOT = os.getenv("UPLOAD_ZIP_SNAPSHOT", "1") not in ("0", "false", "False")

# Chunk size for large uploads
CHUNK = 8 * 1024 * 1024  # 8MB


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
    """
    Prefer refresh-token flow; fall back to access token if needed.
    """
    if DBX_APP_KEY and DBX_APP_SECRET and DBX_REFRESH_TOKEN:
        return dropbox.Dropbox(
            oauth2_refresh_token=DBX_REFRESH_TOKEN,
            app_key=DBX_APP_KEY,
            app_secret=DBX_APP_SECRET,
            timeout=300,
        )
    if DBX_ACCESS_TOKEN:
        return dropbox.Dropbox(DBX_ACCESS_TOKEN, timeout=300)
    raise RuntimeError(
        "Dropbox credentials missing. Set either "
        "(DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN) "
        "or DROPBOX_ACCESS_TOKEN."
    )


def _ensure_folder(dbx: dropbox.Dropbox, path: str) -> None:
    if not path.startswith("/"):
        path = "/" + path
    try:
        dbx.files_get_metadata(path)
    except ApiError:
        try:
            dbx.files_create_folder_v2(path)
        except ApiError:
            # If it already exists or parent missing, next uploads may still create subpaths;
            # we'll rely on file uploads below. This keeps things resilient.
            pass


def _dbx_put_bytes(dbx: dropbox.Dropbox, dropbox_path: str, data: bytes) -> None:
    if not dropbox_path.startswith("/"):
        dropbox_path = "/" + dropbox_path
    dbx.files_upload(data, dropbox_path, mode=WriteMode("overwrite"), mute=True)


def _dbx_put_file(dbx: dropbox.Dropbox, local_path: Path, dropbox_path: str) -> None:
    if not dropbox_path.startswith("/"):
        dropbox_path = "/" + dropbox_path
    size = local_path.stat().st_size
    if size < 140 * 1024 * 1024:
        with local_path.open("rb") as f:
            dbx.files_upload(f.read(), dropbox_path, mode=WriteMode("overwrite"), mute=True)
        return

    # Chunked upload for large files
    with local_path.open("rb") as f:
        session = dbx.files_upload_session_start(f.read(CHUNK))
        cursor = UploadSessionCursor(session_id=session.session_id, offset=f.tell())
        commit = CommitInfo(path=dropbox_path, mode=WriteMode("overwrite"), mute=True)
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
    Build a full backup and upload to Dropbox:
      /<ROOT>/<YYYY-MM-DD_HH-MM-SSZ>/
        database/student_palace.db
        site-files/static/uploads/**/*
        manifest.json
        (optional) student-palace-backup-<YYYYmmdd-HHMMSSZ>.zip

    Returns the Dropbox folder path created.
    """
    # Lazy import to avoid circular imports
    from db import DB_PATH

    # Find project root (where /static exists)
    project_root = Path(__file__).resolve().parent
    for _ in range(6):
        if (project_root / "static").exists():
            break
        project_root = project_root.parent

    uploads_dir = project_root / "static" / "uploads"
    db_path = Path(DB_PATH)

    # Build ZIP in memory and compute manifest
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
    _ensure_folder(dbx, base)
    _ensure_folder(dbx, f"{base}/database")
    _ensure_folder(dbx, f"{base}/site-files/static/uploads")

    # 1) DB (extracted)
    if db_path.exists():
        _dbx_put_file(dbx, db_path, f"{base}/database/student_palace.db")

    # 2) Uploads (extracted)
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

    # 3) manifest.json (extracted copy)
    manifest_bytes = json.dumps({
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "database": {"path": str(db_path), **db_info},
        "uploads": {"path": str(uploads_dir), **uploads_info},
        "note": "This is a duplicate of the manifest stored inside the .zip"
    }, indent=2, sort_keys=True).encode("utf-8")
    _dbx_put_bytes(dbx, f"{base}/manifest.json", manifest_bytes)

    # 4) Optional ZIP snapshot
    if UPLOAD_ZIP_SNAPSHOT:
        zip_name = f"student-palace-backup-{ts_file}.zip"
        _dbx_put_bytes(dbx, f"{base}/{zip_name}", buf.getvalue())

    return "/" + base.lstrip("/")


if __name__ == "__main__":
    try:
        path = run_backup()
        print("✅ Backup uploaded to:", path)
    except (AuthError, ApiError) as e:
        print("ERROR: Dropbox auth/upload failed. Check keys/refresh token/scopes.")
        print(repr(e))
        raise
    except Exception as e:
        print("ERROR:", e)
        raise
