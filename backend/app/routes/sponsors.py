"""Партньори/спонсори: публичен списък + админ API.

Публично:  GET /api/sponsors                    видимите, в избрания ред
Админ:     GET    /api/admin/sponsors           всички
           POST   /api/admin/sponsors           нов (multipart: name, headline, body, website, is_visible, logo)
           PATCH  /api/admin/sponsors/<id>      промяна (същите полета; logo е по избор)
           POST   /api/admin/sponsors/<id>/move {"direction": "up" | "down"}
           DELETE /api/admin/sponsors/<id>
Логото се пази като PNG (прозрачността се запазва), най-много 600x400 px.
"""
import os
import re
import uuid

from flask import Blueprint, current_app, jsonify, request
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func

from app import db
from app.auth import check_admin
from app.models import Sponsor
from app.routes.matches import clean_https_url
from app.routes.uploads import MAX_PIXELS, READABLE_FORMATS, UNSUPPORTED_MESSAGE

sponsors_bp = Blueprint("sponsors", __name__)
admin_sponsors_bp = Blueprint("admin_sponsors", __name__)
admin_sponsors_bp.before_request(check_admin)

MAX_NAME, MAX_HEADLINE, MAX_BODY = 80, 160, 3000
LOGO_BOX = (600, 400)


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _logo_url(sponsor):
    return f"/uploads/{sponsor.logo_name}.png"


def public_dict(s):
    return {"name": s.name, "headline": s.headline, "body": s.body,
            "website": s.website, "logo": _logo_url(s)}


def admin_dict(s):
    data = public_dict(s)
    data.update({"id": s.id, "is_visible": bool(s.is_visible)})
    return data


def _ordered():
    return Sponsor.query.order_by(Sponsor.sort_order, Sponsor.id).all()


def _save_logo(file):
    """(име, None) при успех или (None, текст на грешката)."""
    try:
        img = Image.open(file.stream, formats=READABLE_FORMATS)
        if img.width * img.height > MAX_PIXELS:
            return None, "Снимката е с твърде голяма резолюция."
        img.load()
        img = ImageOps.exif_transpose(img).convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None, UNSUPPORTED_MESSAGE
    img.thumbnail(LOGO_BOX, Image.Resampling.LANCZOS)  # не уголемява
    folder = current_app.config["UPLOAD_DIR"]
    os.makedirs(folder, exist_ok=True)
    name = uuid.uuid4().hex[:20]
    img.save(os.path.join(folder, f"{name}.png"), "PNG", optimize=True)
    return name, None


def _remove_logo(name):
    if not name:
        return
    try:
        os.remove(os.path.join(current_app.config["UPLOAD_DIR"], f"{name}.png"))
    except OSError:
        pass


def _apply(sponsor, form):
    """Проверява текстовите полета и ги слага върху спонсора. Връща речник с грешки."""
    errors = {}

    name = re.sub(r"\s+", " ", (form.get("name") or "").strip())
    if not name:
        errors["name"] = "Въведете име на компанията."
    elif len(name) > MAX_NAME:
        errors["name"] = f"Максимум {MAX_NAME} символа."

    headline = re.sub(r"\s+", " ", (form.get("headline") or "").strip())
    if len(headline) > MAX_HEADLINE:
        errors["headline"] = f"Максимум {MAX_HEADLINE} символа."

    body = (form.get("body") or "").replace("\r\n", "\n").strip()
    if len(body) > MAX_BODY:
        errors["body"] = f"Максимум {MAX_BODY} символа."

    website = (form.get("website") or "").strip()
    if website:
        website = clean_https_url(website)
        if website is None:
            errors["website"] = "Въведете пълен адрес, който започва с https://"

    if not errors:
        sponsor.name, sponsor.headline, sponsor.body = name, headline, body
        sponsor.website = website or ""
        sponsor.is_visible = (form.get("is_visible") or "1") in ("1", "true", "on")
    return errors


# ----------------------------------------------------------------- public ---
@sponsors_bp.get("/sponsors")
def list_sponsors():
    items = [s for s in _ordered() if s.is_visible]
    return jsonify({"ok": True, "sponsors": [public_dict(s) for s in items]})


# ------------------------------------------------------------------ admin ---
@admin_sponsors_bp.get("/admin/sponsors")
def admin_list():
    return jsonify({"ok": True, "sponsors": [admin_dict(s) for s in _ordered()]})


@admin_sponsors_bp.post("/admin/sponsors")
def admin_create():
    sponsor = Sponsor()
    errors = _apply(sponsor, request.form)
    file = request.files.get("logo")
    if file is None or not file.filename:
        errors["logo"] = "Изберете лого."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    logo_name, err = _save_logo(file)
    if err:
        return jsonify({"ok": False, "errors": {"logo": err}}), 400

    sponsor.logo_name = logo_name
    sponsor.sort_order = (db.session.query(func.max(Sponsor.sort_order)).scalar() or 0) + 1
    db.session.add(sponsor)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        _remove_logo(logo_name)
        return _error("Не можа да се запази. Опитайте пак.", 500)
    return jsonify({"ok": True, "sponsor": admin_dict(sponsor)}), 201


@admin_sponsors_bp.patch("/admin/sponsors/<int:sponsor_id>")
def admin_update(sponsor_id):
    sponsor = db.session.get(Sponsor, sponsor_id)
    if sponsor is None:
        return _error("Партньорът не е намерен.", 404)
    errors = _apply(sponsor, request.form)
    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400

    old_logo = None
    new_logo = None
    file = request.files.get("logo")
    if file is not None and file.filename:
        new_logo, err = _save_logo(file)
        if err:
            db.session.rollback()
            return jsonify({"ok": False, "errors": {"logo": err}}), 400
        old_logo, sponsor.logo_name = sponsor.logo_name, new_logo
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        _remove_logo(new_logo)
        return _error("Не можа да се запази. Опитайте пак.", 500)
    _remove_logo(old_logo)
    return jsonify({"ok": True, "sponsor": admin_dict(sponsor)})


@admin_sponsors_bp.post("/admin/sponsors/<int:sponsor_id>/move")
def admin_move(sponsor_id):
    data = request.get_json(silent=True) or {}
    if data.get("direction") not in ("up", "down"):
        return _error("Невалидна заявка.")
    items = _ordered()
    index = next((i for i, s in enumerate(items) if s.id == sponsor_id), None)
    if index is None:
        return _error("Партньорът не е намерен.", 404)
    other = index - 1 if data["direction"] == "up" else index + 1
    if 0 <= other < len(items):
        items[index], items[other] = items[other], items[index]
    for position, s in enumerate(items, start=1):  # подреждането се презаписва последователно
        s.sort_order = position
    db.session.commit()
    return jsonify({"ok": True, "sponsors": [admin_dict(s) for s in items]})


@admin_sponsors_bp.delete("/admin/sponsors/<int:sponsor_id>")
def admin_delete(sponsor_id):
    sponsor = db.session.get(Sponsor, sponsor_id)
    if sponsor is None:
        return _error("Партньорът не е намерен.", 404)
    logo = sponsor.logo_name
    db.session.delete(sponsor)
    db.session.commit()
    _remove_logo(logo)
    return jsonify({"ok": True})
