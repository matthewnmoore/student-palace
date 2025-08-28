import os

# Render-friendly defaults
DB_PATH = os.environ.get("DB_PATH", "/opt/uploads/student_palace.db")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/opt/uploads")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_DEBUG = os.environ.get("ADMIN_DEBUG", "0") == "1"

# Ensure dirs exist even if a persistent disk is mounted
import pathlib
pathlib.Path(UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    pathlib.Path(db_dir).mkdir(parents=True, exist_ok=True)
