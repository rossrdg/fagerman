import re
from datetime import timedelta

from flask import Blueprint, jsonify, request

from app import db
from app.auth import (
    csrf_token, current_user, login_user, logout_user, owner_required,
)
from app.models import ROLE_COACH, ROLE_HEAD_COACH, ROLE_OWNER, AdminUser, utcnow

auth_bp = Blueprint("auth", __name__)

MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 8
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")

# Checked when the username does not exist, so the response time is the same.
_DUMMY = AdminUser(password_hash="")
_DUMMY.set_password("not-a-real-password")


def _err(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _me_payload(user):
    return {"ok": True, "user": user.to_dict(), "csrf": csrf_token()}


# ---------- login / logout / me ----------

@auth_bp.post("/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip().lower()
    password = str(data.get("password") or "")
    user = AdminUser.query.filter_by(username=username).first()
    now = utcnow()

    if user and user.locked_until and user.locked_until > now:
        return _err("Твърде много грешни опити. Опитайте отново след няколко минути.", 429)

    valid = (user.check_password(password) if user else _DUMMY.check_password(password))
    if not (user and user.is_active and valid):
        if user:
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= MAX_FAILED:
                user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                user.failed_attempts = 0
            db.session.commit()
        return _err("Грешно потребителско име или парола.", 401)

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    db.session.commit()
    login_user(user)
    return jsonify(_me_payload(user))


@auth_bp.post("/auth/logout")
def logout():
    logout_user()
    return jsonify({"ok": True})


@auth_bp.get("/auth/me")
def me():
    user = current_user()
    if user is None:
        return _err("Не сте влезли.", 401)
    return jsonify(_me_payload(user))


# ---------- account management (owner only) ----------

def _valid_password(password):
    return isinstance(password, str) and len(password) >= MIN_PASSWORD


@auth_bp.get("/admin/users")
@owner_required
def list_users():
    users = AdminUser.query.order_by(AdminUser.role.desc(), AdminUser.username).all()
    return jsonify({"ok": True, "users": [u.to_dict() for u in users]})


@auth_bp.post("/admin/users")
@owner_required
def create_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip().lower()
    display_name = str(data.get("display_name") or "").strip()[:80]
    password = data.get("password")
    errors = {}
    if not USERNAME_RE.match(username):
        errors["username"] = "3–40 символа: малки латински букви, цифри, точка, тире или долна черта."
    elif AdminUser.query.filter_by(username=username).first():
        errors["username"] = "Това потребителско име вече е заето."
    if not _valid_password(password):
        errors["password"] = f"Паролата трябва да е поне {MIN_PASSWORD} символа."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    user = AdminUser(username=username, display_name=display_name or username, role=ROLE_COACH)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({"ok": True, "user": user.to_dict()}), 201


def _coach_or_error(user_id):
    """Only coach accounts are managed through the API; the owner never
    changes or removes himself here (use the command line for that)."""
    user = db.session.get(AdminUser, user_id)
    if user is None:
        return None, _err("Потребителят не е намерен.", 404)
    if user.role == ROLE_OWNER:
        return None, _err("Акаунтът на главния администратор не се променя оттук.", 403)
    return user, None


@auth_bp.patch("/admin/users/<int:user_id>")
@owner_required
def update_user(user_id):
    user, error = _coach_or_error(user_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}

    if "display_name" in data:
        user.display_name = str(data["display_name"] or "").strip()[:80] or user.username
    if "role" in data:
        if data["role"] not in (ROLE_COACH, ROLE_HEAD_COACH):
            return _err("Невалидна роля.")
        if data["role"] == ROLE_HEAD_COACH:
            # Има само един главен треньор: предишният става обикновен треньор.
            for other in AdminUser.query.filter(AdminUser.role == ROLE_HEAD_COACH, AdminUser.id != user.id).all():
                other.role = ROLE_COACH
        user.role = data["role"]
    if "is_active" in data:
        user.is_active = bool(data["is_active"])
        if not user.is_active:
            user.token_version += 1  # kicks out an open session
    if "password" in data:
        if not _valid_password(data["password"]):
            return jsonify({"ok": False, "errors": {
                "password": f"Паролата трябва да е поне {MIN_PASSWORD} символа."}}), 400
        user.set_password(data["password"])  # also logs the coach out everywhere
        user.failed_attempts = 0
        user.locked_until = None
    db.session.commit()
    return jsonify({"ok": True, "user": user.to_dict()})


@auth_bp.delete("/admin/users/<int:user_id>")
@owner_required
def delete_user(user_id):
    user, error = _coach_or_error(user_id)
    if error:
        return error
    from app.routes.coaches import profile_photo_names  # снимката на профила се трие заедно с акаунта
    from app.gallery_utils import remove_files

    photo_names = profile_photo_names(user)
    db.session.delete(user)  # профилът (CoachProfile) се трие каскадно
    db.session.commit()
    remove_files(photo_names)
    return jsonify({"ok": True})
