"""Шифровано съхранение на документите за картотекиране.

Файловете са в DOCS_DIR (извън публичните папки), шифровани с Fernet (ключ DOCS_KEY). Снимките се
въртят според EXIF, смаляват се и се записват като JPEG; PDF се приема като е. Оригиналното име
на файла никога не се ползва. Достъпът е само през проверени адреси (routes/documents.py)."""
import io
import os
import re
import uuid

from cryptography.fernet import Fernet, InvalidToken
from flask import Response, current_app
from PIL import Image, UnidentifiedImageError

from app.routes.uploads import MAX_PIXELS, READABLE_FORMATS, UNSUPPORTED_MESSAGE, _to_rgb

MAX_BYTES = 20 * 1024 * 1024
MAX_FILES_PER_DOC = 5
IMAGE_SIDE = 2200
_NAME_RE = re.compile(r"^[0-9a-f]{24}$")


class StorageError(Exception):
    """Съобщение, което може да се покаже на потребителя."""


def _docs_dir():
    folder = current_app.config["DOCS_DIR"]
    os.makedirs(folder, exist_ok=True)
    return folder


def _fernet():
    key = (current_app.config.get("DOCS_KEY") or "").strip()
    if not key:
        if current_app.config.get("SESSION_COOKIE_SECURE"):
            raise StorageError("Документите не могат да се запазват: не е настроен ключ за шифроване (DOCS_KEY).")
        # Само за локална разработка: ключ във файл до документите.
        key_path = os.path.join(_docs_dir(), "dev.key")
        if not os.path.exists(key_path):
            with open(key_path, "wb") as fh:
                fh.write(Fernet.generate_key())
        with open(key_path, "rb") as fh:
            key = fh.read().decode().strip()
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError):
        raise StorageError("Ключът за шифроване (DOCS_KEY) е невалиден.") from None


def _path(name):
    if not _NAME_RE.match(name or ""):
        raise StorageError("Невалиден файл.")
    return os.path.join(_docs_dir(), name + ".bin")


def _prepare(data):
    """(payload, mime) от качените байтове; StorageError ако не е снимка или PDF."""
    if data[:5] == b"%PDF-":
        return data, "application/pdf"
    try:
        img = Image.open(io.BytesIO(data), formats=READABLE_FORMATS)
        if img.width * img.height > MAX_PIXELS:
            raise StorageError("Снимката е с твърде голяма резолюция.")
        img.load()
        rgb = _to_rgb(img)
    except StorageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise StorageError(UNSUPPORTED_MESSAGE.replace("Опитайте с JPG, PNG или HEIC.", "Качете снимка (JPG, PNG, HEIC) или PDF.")) from None
    rgb.thumbnail((IMAGE_SIDE, IMAGE_SIDE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=85, optimize=True, progressive=True)
    return out.getvalue(), "image/jpeg"


def save_upload(file_storage):
    """Валидира, шифрова и записва качен файл. Връща (име, mime, размер)."""
    if file_storage is None or not file_storage.filename:
        raise StorageError("Не е избран файл.")
    data = file_storage.stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise StorageError("Файлът е над 20 MB.")
    if not data:
        raise StorageError("Файлът е празен.")
    payload, mime = _prepare(data)
    fernet = _fernet()
    name = uuid.uuid4().hex[:24]
    path = _path(name)
    with open(path + ".tmp", "wb") as fh:
        fh.write(fernet.encrypt(payload))
    os.replace(path + ".tmp", path)
    return name, mime, len(payload)


def read_file(name):
    try:
        with open(_path(name), "rb") as fh:
            token = fh.read()
    except FileNotFoundError:
        raise StorageError("Файлът не е намерен.") from None
    try:
        return _fernet().decrypt(token)
    except InvalidToken:
        raise StorageError("Файлът не може да се прочете (грешен ключ за шифроване).") from None


def delete_files(names):
    """Трие файловете; грешките се пренебрегват (редът в базата вече е махнат)."""
    for name in names:
        try:
            os.remove(_path(name))
        except (OSError, StorageError):
            pass


def file_response(name, mime, label="document"):
    """Разшифрован файл като отговор: без кеш и без „гадаене“ на типа."""
    data = read_file(name)
    ext = "pdf" if mime == "application/pdf" else "jpg"
    response = Response(data, mimetype=mime)
    response.headers["Content-Disposition"] = f'inline; filename="{label}.{ext}"'
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
