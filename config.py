# config.py
from __future__ import annotations
import os, pathlib
from datetime import timedelta

SECRET_KEY  = os.environ.get("SECRET_KEY", "change-me-in-prod")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_DEBUG = os.environ.get("ADMIN_DEBUG", "0") == "1"

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
STATIC_DIR   = PROJECT_ROOT / "static"

# --- House uploads ---
HOUSE_UPLOAD_FOLDER_PATH = STATIC_DIR / "uploads" / "houses"
HOUSE_UPLOAD_FOLDER_PATH.mkdir(parents=True, exist_ok=True)
HOUSE_UPLOAD_FOLDER = str(HOUSE_UPLOAD_FOLDER_PATH)

# --- Room uploads (NEW) ---
ROOM_UPLOAD_FOLDER_PATH = STATIC_DIR / "uploads" / "rooms"
ROOM_UPLOAD_FOLDER_PATH.mkdir(parents=True, exist_ok=True)
ROOM_UPLOAD_FOLDER = str(ROOM_UPLOAD_FOLDER_PATH)

print(f"[config] PROJECT_ROOT={PROJECT_ROOT}")
print(f"[config] STATIC_DIR={STATIC_DIR}")
print(f"[config] HOUSE_UPLOAD_FOLDER={HOUSE_UPLOAD_FOLDER}")
print(f"[config] ROOM_UPLOAD_FOLDER={ROOM_UPLOAD_FOLDER}")

MAX_CONTENT_LENGTH = 6 * 1024 * 1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
PERMANENT_SESSION_LIFETIME = timedelta(days=30)
# SESSION_COOKIE_SECURE = True  # when you’re ready
