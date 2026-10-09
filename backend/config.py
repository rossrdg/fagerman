import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    # SQLite file lives next to the backend code during local dev.
    # On superhosting.bg this can later point to the writable path
    # your cPanel account gives you, or be swapped for MySQL (which
    # cPanel plans usually include) by changing this one value.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'fagerman.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")

    # Comma-separated list of allowed origins for the frontend during
    # local dev, e.g. "http://localhost:8000,http://127.0.0.1:8000"
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
