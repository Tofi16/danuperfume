"""
config.py
Centralized environment configuration for the Danu Perfume Flask application.
Loads values from the .env file using python-dotenv.
"""

import os
import secrets
from dotenv import load_dotenv

# Load environment variables from .env file at project root
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    """Base configuration shared across all environments."""

    # --- Security ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-fallback-secret-key")

    # CSRF protection (Flask-WTF). Tokens are auto-injected via the
    # `csrf_token()` Jinja helper once CSRFProtect(app) is initialized in app.py.
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # tokens don't expire mid-checkout on a slow connection

    # Session / auth cookie hardening.
    SESSION_COOKIE_HTTPONLY = True      # JS (and any XSS) cannot read the session cookie
    SESSION_COOKIE_SAMESITE = "Lax"     # blocks the cookie being sent on cross-site POSTs
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV", "production") == "production"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = os.environ.get("FLASK_ENV", "production") == "production"

    # --- Database (Neon PostgreSQL in production; SQLite fallback for local dev) ---
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

    # --- Cloudinary media storage (optional) ---
    CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL")
    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")

    # --- Default Admin Accounts (created automatically on first run) ---
    # SECURITY: no hardcoded fallback password anymore ("#Danu1122" was sitting in
    # the public GitHub repo, which meant anyone could log in as Danuta if the env
    # var was ever unset). If ADMIN_PASSWORD_DANUTA / ADMIN_PASSWORD_TOFIK aren't
    # set in the environment, a random password is generated at startup and
    # printed ONCE to the server logs, so there's never a guessable default.
    GENERATED_ADMIN_PASSWORDS = {}  # populated at startup if any env var was missing

    @staticmethod
    def _admin_password(env_key):
        pw = os.environ.get(env_key)
        if pw:
            return pw
        generated = secrets.token_urlsafe(9)
        Config.GENERATED_ADMIN_PASSWORDS[env_key] = generated
        return generated

    # Each tuple: (username, full_name, password, role)
    # role: "super_admin" (full access) or "order_manager" (orders/delivery only)
    ADMIN_ACCOUNTS = [
        ("Danuta", "Danuta", _admin_password.__func__("ADMIN_PASSWORD_DANUTA"), "super_admin"),
        ("Tofik", "Tofik", _admin_password.__func__("ADMIN_PASSWORD_TOFIK"), "order_manager"),
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
    SESSION_COOKIE_SECURE = False  # localhost is plain http, so this must stay off


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
