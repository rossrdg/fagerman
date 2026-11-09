"""Вход за родителите. Отделен от админ входа: други ключове в сесията (pid/ptv/pcsrf),
затова родителска сесия никога не минава през check_admin."""
import hmac
import secrets
from functools import wraps

from flask import g, jsonify, request, session

from app import db
from app.models import ParentAccount


def _error(message, status, code=None):
    body = {"ok": False, "error": message}
    if code:
        body["code"] = code
    return jsonify(body), status


def current_parent():
    """Влезлият родител или None. Проверява се в базата при всяка заявка: изключен акаунт
    или нова парола прекратяват сесията веднага."""
    if "_parent" in g:
        return g._parent
    parent = None
    pid = session.get("pid")
    if pid:
        candidate = db.session.get(ParentAccount, pid)
        if candidate and candidate.is_active and session.get("ptv") == candidate.token_version:
            parent = candidate
        else:
            session.clear()
    g._parent = parent
    return parent


def login_parent(parent):
    session.clear()  # нова сесия при вход (без session fixation)
    session["pid"] = parent.id
    session["ptv"] = parent.token_version
    session["pcsrf"] = secrets.token_urlsafe(32)
    session.permanent = True
    g._parent = parent


def logout_parent():
    session.clear()
    g._parent = None


def parent_csrf_token():
    return session.get("pcsrf", "")


def _csrf_ok():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    expected = session.get("pcsrf", "")
    return bool(expected) and hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), expected)


def parent_pending(parent):
    """Родителят още трябва да смени паролата или да потвърди политиката."""
    return bool(parent.must_change_password or parent.consent_at is None)


def parent_required(view=None, allow_pending=False):
    """Влязъл родител. allow_pending=True за смяната на парола (преди да е завършила)."""
    def decorate(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            parent = current_parent()
            if parent is None:
                return _error("Трябва да влезете.", 401)
            if not _csrf_ok():
                return _error("Невалидна заявка (CSRF). Презаредете страницата.", 403)
            if not allow_pending and parent_pending(parent):
                return _error("Първо сменете паролата си.", 403, code="password_change_required")
            return func(*args, **kwargs)
        return wrapper
    return decorate(view) if view is not None else decorate
