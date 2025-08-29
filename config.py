# config.py
from __future__ import annotations

import os
import pathlib
from datetime import timedelta

# -----------------------------------------------------------------------------
# Secrets & tokens (set these in Render → Environment)
# -----------------------------------------------------------------------------
SECRET_KEY  = os.environ.get("SECRET_KEY", "change-me-in-prod")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# -----------------------------------------------------------------------------
# File paths (repo-local; no /opt/uploads anywhere)
# -----------------------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
STATIC_DIR   = PROJECT_ROOT / "static"

# Image upload target under Flask static so it's writable & servable
UPLOAD_FOLDER_PATH = STATIC_DIR / "uploads" / "houses"
UPLOAD_FOLDER_PATH.mkdir(parents=True, exist_ok=True)

# Some code expects a plain string:
UPLOAD_FOLDER = str(UPLOAD_FOLDER_PATH)

# Helpful boot log to verify in Render logs which paths are used
print(f"[config] PROJECT_ROOT={PROJECT_ROOT}")
print(f"[config] STATIC_DIR={STATIC_DIR}")
print(f"[config] UPLOAD_FOLDER={UPLOAD_FOLDER}")

# -----------------------------------------------------------------------------
# Flask settings
# -----------------------------------------------------------------------------
MAX_CONTENT_LENGTH = 6 * 1024 * 1024  # 6 MB request cap
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
PERMANENT_SESSION_LIFETIME = timedelta(days=30)
# Enable later when custom domains + SSL are live:
# SESSION_COOKIE_SECURE = True
