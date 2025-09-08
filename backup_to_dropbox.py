import os, sys, tarfile, time, tempfile, pathlib
import dropbox
from dropbox.exceptions import ApiError

# What to back up
UPLOADS_DIR = "/opt/render/project/src/static/uploads"  # contains houses/, rooms/ (symlink), and the DB inside houses/
# Where to put it in Dropbox (root-relative)
DBX_DEST_DIR = "/StudentPalace/backups"

def main():
    token = os.environ.get("DROPBOX_TOKEN") or os.environ.get("DROPBOX_ACCESS_TOKEN")
    if not token:
        print("ERROR: Set env var DROPBOX_TOKEN with a Dropbox access token.", file=sys.stderr)
        sys.exit(1)

    src = pathlib.Path(UPLOADS_DIR)
    if not src.exists():
        print(f"ERROR: Source path not found: {UPLOADS_DIR}", file=sys.stderr)
        sys.exit(2)

    ts = time.strftime("%Y%m%d-%H%M%S")
    archive_name = f"student-palace-backup-{ts}.tar.gz"
    tmp_path = os.path.join(tempfile.gettempdir(), archive_name)

    print(f"Creating archive: {tmp_path}")
    # tar.add(..., recursive=True) follows symlinks by default and stores their targets,
    # which is what we want (capture rooms/ content even if it's a symlink).
    with tarfile.open(tmp_path, "w:gz") as tar:
        tar.add(UPLOADS_DIR, arcname="uploads")

    dbx = dropbox.Dropbox(token)

    # Ensure destination folder exists (create if missing)
    try:
        dbx.files_get_metadata(DBX_DEST_DIR)
    except ApiError:
        try:
            dbx.files_create_folder_v2(DBX_DEST_DIR)
        except ApiError:
            pass  # If it already exists or another race happened, we’ll keep going

    dropbox_path = f"{DBX_DEST_DIR}/{archive_name}"
    print(f"Uploading to Dropbox: {dropbox_path}")
    with open(tmp_path, "rb") as f:
        dbx.files_upload(
            f.read(),
            dropbox_path,
            mode=dropbox.files.WriteMode.add,
            mute=True,
        )

    print("✅ Backup uploaded:", dropbox_path)

if __name__ == "__main__":
    main()
