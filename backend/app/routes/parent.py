"""Родителски портал — API (/api/parent/*).

  POST /parent/login            имейл + парола
  POST /parent/logout
  GET  /parent/me               кой съм, трябва ли смяна на парола/съгласие, CSRF токен
  POST /parent/change-password  текуща + нова парола (+ съгласие при първия път)
  GET  /parent/children         децата на родителя (без архивираните)
"""
from datetime import timedelta

from flask import Blueprint, jsonify, request

from app import db
from app.models import ParentAccount, Player, utcnow
from app.parent_auth import (
    current_parent, login_parent, logout_parent, parent_csrf_token, parent_pending, parent_required,
)
from app.documents_catalog import ensure_set, summary as docs_summary
from app.player_utils import parent_child_dict
from app.team_utils import get_season_end_year, season_text

parent_bp = Blueprint("parent", __name__)

MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 8

# Проверява се и когато имейлът не съществува, за да е еднакво времето на отговора.
_DUMMY = ParentAccount(password_hash="")
_DUMMY.set_password("not-a-real-password")


def _err(message, status=400, code=None):
    body = {"ok": False, "error": message}
    if code:
        body["code"] = code
    return jsonify(body), status


def _me(parent):
    return {
        "ok": True,
        "parent": {"name": parent.display_name, "email": parent.email},
        "must_change_password": bool(parent.must_change_password),
        "needs_consent": parent.consent_at is None,
        "csrf": parent_csrf_token(),
    }


@parent_bp.post("/parent/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")
    parent = ParentAccount.query.filter_by(email=email).first()
    now = utcnow()

    if parent and parent.locked_until and parent.locked_until > now:
        return _err("Твърде много грешни опити. Опитайте отново след няколко минути.", 429)

    valid = parent.check_password(password) if parent else _DUMMY.check_password(password)
    if parent and valid and not parent.is_active:
        return _err("Достъпът до този акаунт е спрян. Свържете се с академията.", 403, code="access_suspended")
    if not (parent and parent.is_active and valid):
        if parent:
            parent.failed_attempts = (parent.failed_attempts or 0) + 1
            if parent.failed_attempts >= MAX_FAILED:
                parent.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                parent.failed_attempts = 0
            db.session.commit()
        return _err("Грешен имейл или парола.", 401)

    if parent.temp_password_expired:
        return _err("Временната парола е изтекла. Свържете се с академията за нова.", 401, code="temp_expired")

    parent.failed_attempts = 0
    parent.locked_until = None
    parent.last_login_at = now
    db.session.commit()
    login_parent(parent)
    return jsonify(_me(parent))


@parent_bp.post("/parent/logout")
def logout():
    logout_parent()
    return jsonify({"ok": True})


@parent_bp.get("/parent/me")
def me():
    parent = current_parent()
    if parent is None:
        return _err("Не сте влезли.", 401)
    return jsonify(_me(parent))


@parent_bp.post("/parent/change-password")
@parent_required(allow_pending=True)
def change_password():
    parent = current_parent()
    data = request.get_json(silent=True) or {}
    current, new = data.get("current_password"), data.get("new_password")
    errors = {}
    if not isinstance(current, str) or not parent.check_password(current):
        errors["current_password"] = "Текущата парола не е вярна."
    if not isinstance(new, str) or len(new) < MIN_PASSWORD:
        errors["new_password"] = f"Паролата трябва да е поне {MIN_PASSWORD} символа."
    elif isinstance(current, str) and new == current:
        errors["new_password"] = "Новата парола трябва да е различна от текущата."
    if parent.consent_at is None and data.get("consent") is not True:
        errors["consent"] = "За да продължите, потвърдете Политиката за поверителност."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    parent.set_password(new)  # вдига token_version и сваля „временна“
    if parent.consent_at is None:
        parent.consent_at = utcnow()
    db.session.commit()
    login_parent(parent)  # новата сесия е с новия token_version
    return jsonify(_me(parent))


def _child_with_docs(player, season_end):
    data = parent_child_dict(player, season_end)
    card, docs = ensure_set(player, season_end)
    data["docs"] = docs_summary(card, docs)
    return data


@parent_bp.get("/parent/children")
@parent_required
def children():
    parent = current_parent()
    season_end = get_season_end_year()
    players = (Player.query.filter_by(parent_id=parent.id, archived=False)
               .order_by(Player.child_name).all())
    children_data = [_child_with_docs(p, season_end) for p in players]
    db.session.commit()
    return jsonify({
        "ok": True,
        "season": season_text(season_end),
        "children": children_data,
    })
