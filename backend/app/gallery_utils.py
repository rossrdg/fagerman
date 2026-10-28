"""Галерия: адреси на снимките, кодове за справка, YouTube линкове, изтриване на файлове."""
import os
import random
import re
from datetime import date
from urllib.parse import parse_qs, urlparse

from flask import current_app

from app.models import Photo

YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
                 "youtube-nocookie.com", "www.youtube-nocookie.com"}


def photo_urls(photo):
    return f"/uploads/{photo.name}.jpg", f"/uploads/{photo.name}-800.jpg"


def new_code(today=None):
    """ДДММГГ + 3 случайни цифри (напр. 271026482). Гарантирано уникален."""
    prefix = (today or date.today()).strftime("%d%m%y")
    taken = {c for (c,) in Photo.query.with_entities(Photo.code).filter(Photo.code.like(prefix + "%")).all()}
    for _ in range(60):
        code = prefix + f"{random.randint(0, 999):03d}"
        if code not in taken:
            return code
    free = [prefix + f"{n:03d}" for n in range(1000) if prefix + f"{n:03d}" not in taken]
    return random.choice(free) if free else None  # всичките 1000 за деня са заети


def parse_youtube(url):
    """Връща 11-символното ID на видеото от YouTube линк, или None."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    candidate = None
    if host in ("youtu.be", "www.youtu.be"):
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host in YOUTUBE_HOSTS:
        parts = [p for p in parsed.path.split("/") if p]
        if parsed.path.rstrip("/") == "/watch":
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
            candidate = parts[1]
    return candidate if candidate and YOUTUBE_ID.match(candidate) else None


def remove_files(names):
    """Трие файловете на снимки (главна + умалена версия). Грешките се пренебрегват."""
    folder = current_app.config["UPLOAD_DIR"]
    for name in names:
        for suffix in (".jpg", "-800.jpg"):
            try:
                os.remove(os.path.join(folder, name + suffix))
            except OSError:
                pass


def album_cover(album):
    """Корицата на албума: избраната, иначе най-новата снимка. None ако няма снимки."""
    if album.cover_photo_id:
        for photo in album.photos:
            if photo.id == album.cover_photo_id:
                return photo
    return album.photos[0] if album.photos else None


def bg_date(value):
    return value.strftime("%d.%m.%Y")
