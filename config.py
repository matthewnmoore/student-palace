import os
import pathlib

# Render-friendly defaults
DB_PATH = os.environ.get("DB_PATH", "/opt/uploads/student_palace.db")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/opt/uploads")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_DEBUG = os.environ.get("ADMIN_DEBUG", "0") == "1"

# Images config
# Stored under Flask static/ so they’re web-accessible as /static/uploads/houses/...
UPLOADS_HOUSES_DIR = os.environ.get("UPLOADS_HOUSES_DIR", "static/uploads/houses")
HOUSE_IMAGES_MAX = int(os.environ.get("HOUSE_IMAGES_MAX", "12"))

# Processing knobs
IMAGE_MAX_WIDTH = int(os.environ.get("IMAGE_MAX_WIDTH", "1600"))
IMAGE_MAX_HEIGHT = int(os.environ.get("IMAGE_MAX_HEIGHT", "1200"))
IMAGE_TARGET_BYTES = int(os.environ.get("IMAGE_TARGET_BYTES", str(200 * 1024)))  # ~200 KB target
WATERMARK_TEXT = os.environ.get("WATERMARK_TEXT", "Student Palace")

# Ensure dirs exist even if a persistent disk is mounted
pathlib.Path(UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    pathlib.Path(db_dir).mkdir(parents=True, exist_ok=True)

# Also ensure the static uploads directory exists (created at runtime too)
pathlib.Path(UPLOADS_HOUSES_DIR).mkdir(parents=True, exist_ok=True)
