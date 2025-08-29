# config.py
from __future__ import annotations

import os
import pathlib
from datetime import timedelta

# -----------------------------------------------------------------------------
# Secrets & tokens
# -----------------------------------------------------------------------------
# Set these in Render → Environment
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-prod")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# -----------------------------------------------------------------------------
# File paths
# -----------------------------------------------------------------------------
# Base directory of the deployed app on Render
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent

# Flask static directory (already in your repo)
STATIC_DIR = PROJECT_ROOT / "static"

# Image upload target (served by Flask static)
# This MUST match where image_helpers.py writes/reads.
UPLOAD_FOLDER = STATIC_DIR / "uploads" / "houses"

# Make sure the directory exists (this path is within your project, so it's writable)
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

# If other code expects a plain string:
UPLOAD_FOLDER = str(UPLOAD_FOLDER)

# -----------------------------------------------------------------------------
# Flask settings
# -----------------------------------------------------------------------------
MAX_CONTENT_LENGTH = 6 * 1024 * 1024  # 6 MB request cap
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
PERMANENT_SESSION_LIFETIME = timedelta(days=30)

# Optional: if you want to force HTTPS in production behind Render's proxy,
# you can add this later after certs are live:
# SESSION_COOKIE_SECURE = True
