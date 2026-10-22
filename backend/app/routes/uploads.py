import os
import uuid

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from PIL import Image, ImageOps, UnidentifiedImageError

# Admin: POST /api/admin/uploads  (no auth yet — protect together with the rest
# of /api/admin/* before production).
uploads_bp = Blueprint("uploads", __name__)
# Public: GET /uploads/<file>
files_bp = Blueprint("upload_files", __name__)

# Any ordinary photo/picture format is accepted — every upload is decoded and re-saved
# as a plain JPEG, so the original file is never served. The list only keeps out the
# exotic formats Pillow can open (e.g. EPS, which runs Ghostscript). SVG is not an
# image Pillow can read, so it is refused too.
Image.init()  # load every format plugin, so the names below exist
READABLE_FORMATS = [f for f in ("JPEG", "PNG", "WEBP", "GIF", "BMP", "DIB", "TIFF", "ICO") if f in Image.OPEN]
MAIN_SIZE = 1600      # longest side of the photo used in articles / Facebook
THUMB_SIZE = 800      # longest side of the card version
MAX_PIXELS = 50_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS * 2


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _to_rgb(img):
    """Applies the phone's rotation and flattens transparency onto white."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return img.convert("RGB")


def _save_jpeg(img, path, longest_side):
    out = img.copy()
    out.thumbnail((longest_side, longest_side), Image.Resampling.LANCZOS)  # never enlarges
    out.save(path, "JPEG", quality=82, optimize=True, progressive=True)
    return out.size


@uploads_bp.post("/admin/uploads")
def upload_image():
    file = request.files.get("image")
    if file is None or not file.filename:
        return _error("Не е избран файл.")

    try:
        img = Image.open(file.stream, formats=READABLE_FORMATS)
        if img.width * img.height > MAX_PIXELS:
            return _error("Снимката е с твърде голяма резолюция.")
        img.load()
        rgb = _to_rgb(img)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return _error("Файлът не е снимка или форматът му не се поддържа. Опитайте с JPG или PNG.")

    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    name = uuid.uuid4().hex[:20]  # random name: the original file name is never used
    width, height = _save_jpeg(rgb, os.path.join(upload_dir, f"{name}.jpg"), MAIN_SIZE)
    _save_jpeg(rgb, os.path.join(upload_dir, f"{name}-800.jpg"), THUMB_SIZE)

    return jsonify({
        "ok": True,
        "url": f"/uploads/{name}.jpg",
        "thumb": f"/uploads/{name}-800.jpg",
        "width": width,
        "height": height,
    }), 201


@files_bp.get("/uploads/<path:filename>")
def serve_upload(filename):
    response = send_from_directory(current_app.config["UPLOAD_DIR"], filename)
    # File names are random and never reused, so browsers may keep them for a year.
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
