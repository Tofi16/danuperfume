"""
config.py
Centralized environment configuration for the Danu Perfume Flask application.
Loads values from the .env file using python-dotenv.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file at project root
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    """Base configuration shared across all environments."""

    # --- Security ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-fallback-secret-key")

    # --- Database ---
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(basedir, 'danu_perfume.db')}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,   # Prevents stale connection errors with Neon's serverless Postgres
        "pool_recycle": 300,
    }

    # --- File Uploads ---
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "static/uploads")
    MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", 5))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

    # --- Default Admin Accounts (created automatically on first run) ---
    # Each tuple: (username, full_name, password)
    ADMIN_ACCOUNTS = [
        ("Danuta", "Danuta", os.environ.get("ADMIN_PASSWORD_DANUTA", "#Danu1122")),
        ("Tofik", "Tofik", os.environ.get("ADMIN_PASSWORD_TOFIK", "#Danu1122")),
    ]

    # --- i18n ---
    LANGUAGES = ["en", "am", "om", "ti"]
    DEFAULT_LANGUAGE = "en"

    # --- Currency ---
    CURRENCY_SYMBOL = "ETB"

    # --- Delivery ---
    DELIVERY_FEE_MIN = float(os.environ.get("DELIVERY_FEE_MIN", 80))
    DELIVERY_FEE_MAX = float(os.environ.get("DELIVERY_FEE_MAX", 250))


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
