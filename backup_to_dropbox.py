cat > backup_to_dropbox.py <<'PY'
import os, sys, tarfile, time, tempfile, pathlib
import dropbox

# Paths
UPLOADS_DIR = "/opt/render/project/src/static/uploads"  # contains houses/, rooms/ and the DB inside houses/
DBX_DEST_DIR = "/StudentPalace/backups"  # Dropbox folder path (root-relative)

token = os.environ.get("DROPBOX_TOKEN") or os.environ.get("DROPBOX_ACCESS_TOKEN")
if not token:
    print("ERROR: Set env var DROPBOX_TOKEN with a Dropbox long-lived access token.", file=sys.stderr)
    sys.exit(1)

ts = time.strftime("%Y%m%d-%H%M%S")
archive_name = f"student-palace-backup-{ts}.tar.gz"

# Build archive in /tmp
tmp_path = os.path.join(tempfile.gettempdir(), archive_name)
src = pathlib.Path(UPLOADS_DIR)

if not src.exists():
    print(f"ERROR: Source path not found: {UPLOADS_DIR}", file=sys.stderr)
    sys.exit(2)

print(f"Creating archive: {tmp_path}")
with tarfile.open(tmp_path, "w:gz") as tar:
    # archive entire uploads/ tree (includes houses/, rooms/ symlink, and DB inside houses/)
    tar.add(UPLOADS_DIR, arcname="uploads")

# Upload to Dropbox
dbx = dropbox.Dropbox(token)
dropbox_path = f"{DBX_DEST_DIR}/{archive_name}"
print(f"Uploading to Dropbox: {dropbox_path}")
with open(tmp_path, "rb") as f:
    dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.add, mute=True)

print("✅ Backup uploaded:", dropbox_path)
PY
