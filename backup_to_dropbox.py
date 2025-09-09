# backup_to_dropbox.py
import os
import sys
import time
import tarfile
import tempfile
import pathlib

import dropbox
from dropbox.exceptions import ApiError, AuthError

# --- What to back up ---
# This folder contains: houses/, rooms/ (symlink), floorplans/, landlord_* dirs, and the SQLite DB under houses/
UPLOADS_DIR = "/opt/render/project/src/static/uploads"

# --- Where to place backups in Dropbox (root-relative path in your Dropbox) ---
DBX_DEST_DIR = "/StudentPalace/backups"


def make_archive(src_dir: str) -> str:
    """Tar+gzip the uploads/ directory into /tmp and return the archive path."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    archive_name = f"student-palace-backup-{ts}.tar.gz"
    tmp_path = os.path.join(tempfile.gettempdir(), archive_name)

    src = pathlib.Path(src_dir)
    if not src.exists():
        print(f"ERROR: Source path not found: {src_dir}", file=sys.stderr)
        sys.exit(2)

    print(f"Creating archive: {tmp_path}")
    # tar.add follows symlinks and includes their targets (desired: include rooms/ content)
    with tarfile.open(tmp_path, "w:gz") as tar:
        tar.add(src_dir, arcname="uploads")

    return tmp_path


def get_dbx_client() -> dropbox.Dropbox:
    """
    Build a Dropbox client using refresh-token flow (non-expiring).
    Requires env vars:
      DROPBOX_APP_KEY
      DROPBOX_APP_SECRET
      DROPBOX_REFRESH_TOKEN
    """
    APP_KEY = os.environ.get("DROPBOX_APP_KEY")
    APP_SECRET = os.environ.get("DROPBOX_APP_SECRET")
    REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN")

    missing = [n for n, v in [
        ("DROPBOX_APP_KEY", APP_KEY),
        ("DROPBOX_APP_SECRET", APP_SECRET),
        ("DROPBOX_REFRESH_TOKEN", REFRESH_TOKEN),
    ] if not v]

    if missing:
        print("ERROR: Missing env vars:", ", ".join(missing), file=sys.stderr)
        sys.exit(1)

    try:
        dbx = dropbox.Dropbox(
            oauth2_refresh_token=REFRESH_TOKEN,
            app_key=APP_KEY,
            app_secret=APP_SECRET,
        )
        # Light ping to verify creds
        dbx.users_get_current_account()
        return dbx
    except AuthError as e:
        print("ERROR: Dropbox auth failed. Check your app key/secret/refresh token.", file=sys.stderr)
        print(e, file=sys.stderr)
        sys.exit(3)


def ensure_folder(dbx: dropbox.Dropbox, folder_path: str) -> None:
    """Create the folder in Dropbox if it doesn't exist."""
    try:
        dbx.files_get_metadata(folder_path)
    except ApiError:
        try:
            dbx.files_create_folder_v2(folder_path)
        except ApiError:
            # If there's a race or it already exists, just continue
            pass


def upload_file(dbx: dropbox.Dropbox, local_path: str, dropbox_folder: str) -> str:
    """Upload a local file to a Dropbox folder; return the Dropbox path."""
    dropbox_path = f"{dropbox_folder}/{os.path.basename(local_path)}"
    file_size = os.path.getsize(local_path)

    # Use simple upload for smaller files, chunked for large ones
    CHUNK_SIZE = 8 * 1024 * 1024  # 8MB
    print(f"Uploading to Dropbox: {dropbox_path} ({file_size} bytes)")

    with open(local_path, "rb") as f:
        if file_size <= CHUNK_SIZE:
            dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.add, mute=True)
        else:
            upload_session_start_result = dbx.files_upload_session_start(f.read(CHUNK_SIZE))
            cursor = dropbox.files.UploadSessionCursor(
                session_id=upload_session_start_result.session_id,
                offset=f.tell()
            )
            commit = dropbox.files.CommitInfo(path=dropbox_path, mode=dropbox.files.WriteMode.add, mute=True)

            while cursor.offset < file_size:
                if (file_size - cursor.offset) <= CHUNK_SIZE:
                    dbx.files_upload_session_finish(f.read(CHUNK_SIZE), cursor, commit)
                else:
                    dbx.files_upload_session_append_v2(f.read(CHUNK_SIZE), cursor)
                    cursor.offset = f.tell()

    return dropbox_path


def main():
    archive_path = make_archive(UPLOADS_DIR)
    dbx = get_dbx_client()
    ensure_folder(dbx, DBX_DEST_DIR)
    dbx_path = upload_file(dbx, archive_path, DBX_DEST_DIR)
    print("✅ Backup uploaded:", dbx_path)


if __name__ == "__main__":
    main()
