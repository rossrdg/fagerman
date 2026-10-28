import os
from pathlib import Path

try:  # lets a local backend/.env file provide the settings below
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'fagerman.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")

    # Admin login session (cookie). In production (https) set
    # SESSION_COOKIE_SECURE=1 and a long random SECRET_KEY in backend/.env.
    SESSION_COOKIE_NAME = "fa_admin"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = int(os.environ.get("SESSION_HOURS", "12")) * 3600

    # Public address of the site, used for absolute links in Facebook share
    # tags (og:url, og:image). Production: https://fa-german.eu
    SITE_URL = os.environ.get("SITE_URL", "")

    # Photos uploaded from the admin (resized JPEGs). Keep this folder out of git
    # and include it in backups. Production: ideally outside the project folder.
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads"))
    MAX_CONTENT_LENGTH = 21 * 1024 * 1024  # largest request body (one photo up to 20 MB + form overhead)

    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")

    # Where the static site (index.html, styles.css, script.js, assets/)
    # lives, relative to this backend folder. Default assumes a sibling
    # "frontend" folder next to "backend":
    FRONTEND_DIR = os.environ.get(
        "FRONTEND_DIR", str(BASE_DIR.parent / "frontend")
    )

    # --- Outgoing email (parent notifications) ---
    # With MAIL_SERVER empty nothing is sent: the email is only printed in the
    # server log ("dry run"), which is what you want while developing locally.
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "465"))
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", True)    # port 465
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", False)   # STARTTLS, port 587
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", os.environ.get("MAIL_USERNAME", ""))
    MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME", "Футболна Академия Герман")
    MAIL_REPLY_TO = os.environ.get("MAIL_REPLY_TO", "")
