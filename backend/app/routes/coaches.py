"""Треньори: управление (главен админ и главен треньор) + публична страница /coaches.

Управление — /api/admin/coaches (главен админ ИЛИ главен треньор):
  GET    /admin/coaches                  треньорите (и главния) с профилите им
  POST   /admin/coaches                  нов треньор: акаунт + профил
  PATCH  /admin/coaches/<id>             име, биография, „показвай на сайта“, отбори
                                         (само за обикновен треньор още: is_active, password)
  POST   /admin/coaches/<id>/photo       снимка (multipart "image"); DELETE я маха
  DELETE /admin/coaches/<id>             трие акаунта и профила (само обикновен треньор)
Публично:
  GET /coaches                           страница с картите на треньорите
  GET /api/coaches/head                  снимката и името на главния треньор (за началната страница)

Главният треньор управлява САМО обикновени треньори (акаунт и профил). Своя профил
(снимка, биография, отбори) редактира, но не и ролята/акаунта си. Акаунтите на главния
треньор и на главния админ се управляват от „Потребители“ (само главен админ)."""
import os
import re
import uuid

from flask import Blueprint, current_app, jsonify, render_template, request
from PIL import Image, UnidentifiedImageError

from app import db
from app.auth import check_admin, current_user
from app.gallery_utils import remove_files
from app.models import (
    ROLE_COACH, ROLE_HEAD_COACH, TEAM_ACTIVE, AdminUser, CoachProfile, Team, TrainingGroup,
)
from app.routes.news import DEFAULT_SHARE_IMAGE, _absolute
from app.routes.uploads import (
    MAIN_SIZE, MAX_PIXELS, READABLE_FORMATS, THUMB_SIZE, UNSUPPORTED_MESSAGE, _save_jpeg, _to_rgb,
)
from app.team_utils import cohort_text, get_season_end_year, sort_key, u_label

admin_coaches_bp = Blueprint("admin_coaches", __name__)
public_coaches_bp = Blueprint("public_coaches", __name__)

MAX_BIO = 600
MIN_PASSWORD = 8
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


@admin_coaches_bp.before_request
def _only_owner_or_head_coach():
    denied = check_admin()
    if denied is not None:
        return denied
    user = current_user()
    if not (user.is_owner or user.is_head_coach):
        return _error("Нямате права за тази операция.", 403)
    return None


# ---------------------------------------------------------------- helpers ---
def _profile(user, create=False):
    """Профилът на акаунта; без ред в базата важат стойностите по подразбиране."""
    if user.profile is None and create:
        profile = CoachProfile()
        user.profile = profile
        if user in db.session:  # нов (още не записан) акаунт влиза в сесията чак при add(user)
            db.session.add(profile)
    return user.profile


def profile_photo_names(user):
    return [user.profile.photo_name] if user.profile is not None and user.profile.photo_name else []


def _teams_of(user):
    profile = user.profile
    return sorted(profile.teams, key=sort_key) if profile is not None else []


def _groups_of(user):
    profile = user.profile
    return sorted(profile.groups, key=lambda g: g.name.casefold()) if profile is not None else []


def coach_dict(user, season_end):
    profile = user.profile
    teams = _teams_of(user)
    groups = _groups_of(user)
    photo = profile.photo_name if profile is not None else None
    return {
        "id": user.id, "username": user.username, "display_name": user.display_name or user.username,
        "role": user.role, "is_head": user.is_head_coach, "is_active": bool(user.is_active),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "bio": profile.bio if profile is not None else "",
        "show_on_site": profile.show_on_site if profile is not None else True,
        "photo": f"/uploads/{photo}-800.jpg" if photo else None,
        "team_ids": [t.id for t in teams],
        "team_labels": [u_label(t, season_end) for t in teams],
        "group_ids": [g.id for g in groups],
        "group_labels": [g.name for g in groups],
    }


def _target(user_id):
    """Треньор или главен треньор; всичко друго (главен админ) не се пипа оттук."""
    user = db.session.get(AdminUser, user_id)
    if user is None or user.role not in (ROLE_COACH, ROLE_HEAD_COACH):
        return None, _error("Треньорът не е намерен.", 404)
    return user, None


def _only_plain_coach(user):
    if user.role != ROLE_COACH:
        return _error("Акаунтът на главния треньор се управлява от главния админ (Потребители).", 403)
    return None


def _clean_text(value, limit):
    if value is not None and not isinstance(value, str):
        return None, "Невалидна стойност."
    value = (value or "").strip()
    if len(value) > limit:
        return None, f"Максимум {limit} символа."
    return value, None


def _apply_profile(user, data, errors):
    """Прилага полетата на профила от заявката (display_name, bio, show_on_site, team_ids)."""
    if "display_name" in data:
        value, err = _clean_text(data["display_name"], 80)
        if err or not value:
            errors["display_name"] = err or "Въведете име."
        else:
            user.display_name = value
    profile_fields = {k for k in ("bio", "show_on_site", "team_ids", "group_ids") if k in data}
    if not profile_fields:
        return
    profile = _profile(user, create=True)
    if "bio" in data:
        value, err = _clean_text(data["bio"], MAX_BIO)
        if err:
            errors["bio"] = err
        else:
            profile.bio = value
    if "show_on_site" in data:
        if not isinstance(data["show_on_site"], bool):
            errors["show_on_site"] = "Невалидна стойност."
        else:
            profile.show_on_site = data["show_on_site"]
    if "team_ids" in data:
        ids = data["team_ids"]
        if not isinstance(ids, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in ids):
            errors["team_ids"] = "Невалиден избор на отбори."
        else:
            teams = Team.query.filter(Team.id.in_(ids)).all() if ids else []
            if len(teams) != len(set(ids)):
                errors["team_ids"] = "Някой от избраните отбори не съществува."
            else:
                profile.teams = teams
    if "group_ids" in data:
        ids = data["group_ids"]
        if not isinstance(ids, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in ids):
            errors["team_ids"] = "Невалиден избор на групи."
        else:
            groups = TrainingGroup.query.filter(TrainingGroup.id.in_(ids)).all() if ids else []
            if len(groups) != len(set(ids)):
                errors["team_ids"] = "Някоя от избраните групи не съществува."
            else:
                profile.groups = groups


# ------------------------------------------------------------------ admin ---
@admin_coaches_bp.get("/admin/coaches")
def admin_list():
    season_end = get_season_end_year()
    users = (AdminUser.query.filter(AdminUser.role.in_([ROLE_COACH, ROLE_HEAD_COACH]))
             .order_by(AdminUser.role.desc(), AdminUser.display_name).all())
    teams = sorted(Team.query.filter_by(status=TEAM_ACTIVE).all(), key=sort_key)
    return jsonify({
        "ok": True,
        "me": current_user().id,
        "coaches": [coach_dict(u, season_end) for u in users],
        "teams": [{"id": t.id, "label": u_label(t, season_end), "cohort": cohort_text(t)} for t in teams],
        "groups": [{"id": g.id, "name": g.name} for g in TrainingGroup.query.order_by(TrainingGroup.name).all()],
    })


@admin_coaches_bp.post("/admin/coaches")
def admin_create():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    username = str(data.get("username") or "").strip().lower()
    password = data.get("password")
    errors = {}
    if not USERNAME_RE.match(username):
        errors["username"] = "3–40 символа: малки латински букви, цифри, точка, тире или долна черта."
    elif AdminUser.query.filter_by(username=username).first():
        errors["username"] = "Това потребителско име вече е заето."
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        errors["password"] = f"Паролата трябва да е поне {MIN_PASSWORD} символа."

    user = AdminUser(username=username, display_name=username, role=ROLE_COACH)
    if "display_name" not in data or not str(data.get("display_name") or "").strip():
        data = {**data, "display_name": username}
    _apply_profile(user, data, errors)
    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400

    user.set_password(password)
    db.session.add(user)
    if user.profile is None:
        user.profile = CoachProfile(user=user)
    db.session.commit()
    return jsonify({"ok": True, "coach": coach_dict(user, get_season_end_year())}), 201


@admin_coaches_bp.patch("/admin/coaches/<int:user_id>")
def admin_update(user_id):
    user, error = _target(user_id)
    if error:
        return error
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")

    errors = {}
    if "is_active" in data or "password" in data:
        denied = _only_plain_coach(user)
        if denied:
            return denied
    _apply_profile(user, data, errors)
    if "is_active" in data:
        if user.id == current_user().id:
            errors["is_active"] = "Не можете да изключите собствения си акаунт."
        else:
            user.is_active = bool(data["is_active"])
            if not user.is_active:
                user.token_version += 1  # прекратява отворената му сесия
    if "password" in data:
        if not isinstance(data["password"], str) or len(data["password"]) < MIN_PASSWORD:
            errors["password"] = f"Паролата трябва да е поне {MIN_PASSWORD} символа."
        else:
            user.set_password(data["password"])  # и излиза от всички сесии
            user.failed_attempts = 0
            user.locked_until = None
    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400
    db.session.commit()
    return jsonify({"ok": True, "coach": coach_dict(user, get_season_end_year())})


@admin_coaches_bp.delete("/admin/coaches/<int:user_id>")
def admin_delete(user_id):
    user, error = _target(user_id)
    if error:
        return error
    denied = _only_plain_coach(user)
    if denied:
        return denied
    names = profile_photo_names(user)
    db.session.delete(user)  # профилът и връзките към отбори се трият каскадно
    db.session.commit()
    remove_files(names)
    return jsonify({"ok": True})


@admin_coaches_bp.post("/admin/coaches/<int:user_id>/photo")
def admin_set_photo(user_id):
    user, error = _target(user_id)
    if error:
        return error
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
        return _error(UNSUPPORTED_MESSAGE)

    folder = current_app.config["UPLOAD_DIR"]
    os.makedirs(folder, exist_ok=True)
    name = uuid.uuid4().hex[:20]
    _save_jpeg(rgb, os.path.join(folder, f"{name}.jpg"), MAIN_SIZE)
    _save_jpeg(rgb, os.path.join(folder, f"{name}-800.jpg"), THUMB_SIZE)

    profile = _profile(user, create=True)
    old = profile.photo_name
    profile.photo_name = name
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        remove_files([name])
        return _error("Снимката не можа да се запази. Опитайте пак.", 500)
    if old:
        remove_files([old])
    return jsonify({"ok": True, "coach": coach_dict(user, get_season_end_year())})


@admin_coaches_bp.delete("/admin/coaches/<int:user_id>/photo")
def admin_remove_photo(user_id):
    user, error = _target(user_id)
    if error:
        return error
    profile = user.profile
    old = profile.photo_name if profile is not None else None
    if profile is not None:
        profile.photo_name = None
        db.session.commit()
    if old:
        remove_files([old])
    return jsonify({"ok": True, "coach": coach_dict(user, get_season_end_year())})


# ----------------------------------------------------------------- public ---
def _visible_coaches():
    """Треньорите на сайта: главният първи, останалите по азбучен ред. Изключените
    акаунти остават; скрит е само който е с махната отметка „Показвай на сайта“."""
    users = AdminUser.query.filter(AdminUser.role.in_([ROLE_COACH, ROLE_HEAD_COACH])).all()
    users = [u for u in users if u.profile is None or u.profile.show_on_site]
    users.sort(key=lambda u: (0 if u.is_head_coach else 1, (u.display_name or u.username).casefold()))
    return users


def _paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


@public_coaches_bp.get("/coaches")
@public_coaches_bp.get("/coaches/")
def coaches_page():
    season_end = get_season_end_year()
    cards = []
    for user in _visible_coaches():
        profile = user.profile
        teams = [t for t in _teams_of(user) if t.status == TEAM_ACTIVE]
        cards.append({
            "name": user.display_name or user.username,
            "is_head": user.is_head_coach,
            "photo": f"/uploads/{profile.photo_name}-800.jpg" if profile is not None and profile.photo_name else None,
            "bio": _paragraphs(profile.bio if profile is not None else ""),
            "teams": [u_label(t, season_end) for t in teams] + [g.name for g in _groups_of(user)],
        })
    return render_template(
        "coaches_page.html", coaches=cards,
        page_url=_absolute("/coaches"), image_url=_absolute(DEFAULT_SHARE_IMAGE),
    )


@public_coaches_bp.get("/api/coaches/head")
def head_coach():
    """Снимка и име на главния треньор — началната страница ги слага в своята секция."""
    for user in _visible_coaches():
        if user.is_head_coach:
            photo = user.profile.photo_name if user.profile is not None else None
            return jsonify({"ok": True, "name": user.display_name or user.username,
                            "photo": f"/uploads/{photo}.jpg" if photo else None})
    return jsonify({"ok": True, "name": None, "photo": None})
