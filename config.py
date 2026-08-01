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

    # --- Database (Neon.tech PostgreSQL) ---
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
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
    # Each tuple: (username, full_name, password, role)
    # role: "super_admin" (full access) or "order_manager" (orders/delivery only)
    ADMIN_ACCOUNTS = [
        ("Danuta", "Danuta", os.environ.get("ADMIN_PASSWORD_DANUTA", "#Danu1122"), "super_admin"),
        ("Tofik", "Tofik", os.environ.get("ADMIN_PASSWORD_TOFIK", "#Danu1122"), "order_manager"),
    ]

    # --- i18n ---
    LANGUAGES = ["en", "am", "om", "ti"]
    DEFAULT_LANGUAGE = "en"

    # --- Currency ---
    CURRENCY_SYMBOL = "ETB"

    # --- Delivery ---
    DELIVERY_FEE_MIN = float(os.environ.get("DELIVERY_FEE_MIN", 80))
    DELIVERY_FEE_MAX = float(os.environ.get("DELIVERY_FEE_MAX", 250))

    # --- Multi-Currency Display (informational only — checkout always charges in ETB) ---
    FX_RATES = {
        "USD": float(os.environ.get("FX_RATE_USD", 0.0075)),
        "EUR": float(os.environ.get("FX_RATE_EUR", 0.0069)),
    }

    # --- Loyalty Points ---
    LOYALTY_POINTS_PER_100_ETB = int(os.environ.get("LOYALTY_POINTS_PER_100_ETB", 5))

    # --- Fraud / Risk Scoring thresholds ---
    RISK_HIGH_ORDER_AMOUNT = float(os.environ.get("RISK_HIGH_ORDER_AMOUNT", 5000))
    RISK_DUPLICATE_WINDOW_MINUTES = int(os.environ.get("RISK_DUPLICATE_WINDOW_MINUTES", 30))


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
