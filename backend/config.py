import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'fagerman.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")

    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")

    # Where the static site (index.html, styles.css, script.js, assets/)
    # lives, relative to this backend folder. Default assumes a sibling
    # "frontend" folder next to "backend":
    FRONTEND_DIR = os.environ.get(
        "FRONTEND_DIR", str(BASE_DIR.parent / "frontend")
    )