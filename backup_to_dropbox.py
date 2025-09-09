# backup_to_dropbox.py
import os, sys, tarfile, time, tempfile, pathlib
import dropbox
from dropbox.exceptions import ApiError, AuthError

# What to back up
UPLOADS_DIR = "/opt/render/project/src/static/uploads"
# Destination folder in Dropbox (root-relative)
DBX_DEST_DIR = "/StudentPalace/backups"


def _make_dbx() -> dropbox.Dropbox:
    """Create an authenticated Dropbox client using refresh token flow."""
    app_key = os.environ.get("DROPBOX_APP_KEY")
    app_secret = os.environ.get("DROPBOX_APP_SECRET")
    refresh_token = os.environ.get("DROPBOX_REFRESH_TOKEN")
    if not (app_key and app_secret and refresh_token):
        raise RuntimeError("Missing Dropbox env vars (APP_KEY/APP_SECRET/REFRESH_TOKEN).")
    return dropbox.Dropbox(
        oauth2_refresh_token=refresh_token,
        app_key=app_key,
        app_secret=app_secret,
    )


def run_backup() -> str:
    """
    Create a .tar.gz archive of the uploads directory and upload it to Dropbox.
    Returns the Dropbox path of the uploaded file.
    """
    src = pathlib.Path(UPLOADS_DIR)
    if not src.exists():
        raise FileNotFoundError(f"Source path not found: {UPLOADS_DIR}")

    ts = time.strftime("%Y%m%d-%H%M%S")
    archive_name = f"student-palace-backup-{ts}.tar.gz"
    tmp_path = os.path.join(tempfile.gettempdir(), archive_name)

    # Create archive in /tmp
    with tarfile.open(tmp_path, "w:gz") as tar:
        tar.add(UPLOADS_DIR, arcname="uploads")

    # Upload to Dropbox
    dbx = _make_dbx()

    # Ensure destination folder exists
    try:
        dbx.files_get_metadata(DBX_DEST_DIR)
    except ApiError:
        try:
            dbx.files_create_folder_v2(DBX_DEST_DIR)
        except ApiError:
            pass  # Ignore if folder already exists

    dropbox_path = f"{DBX_DEST_DIR}/{archive_name}"
    size = os.path.getsize(tmp_path)
    print(f"Uploading to Dropbox: {dropbox_path} ({size} bytes)")

    with open(tmp_path, "rb") as f:
        dbx.files_upload(
            f.read(),
            dropbox_path,
            mode=dropbox.files.WriteMode.add,
            mute=True,
        )

    return dropbox_path


if __name__ == "__main__":
    try:
        path = run_backup()
        print("✅ Backup uploaded:", path)
    except (AuthError, ApiError) as e:
        print("ERROR: Dropbox auth failed. Check keys/refresh token/scopes.")
        print(repr(e))
        sys.exit(2)
    except Exception as e:
        print("ERROR:", e)
        sys.exit(1)
