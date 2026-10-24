"""Login for the admin pages: session helpers and access decorators.

Roles: "owner" (main administrator) and "coach". Everything under the admin
tools needs a logged-in user; managing accounts needs the owner.
"""
import hmac
import secrets
from functools import wraps

from flask import g, jsonify, request, session

from app import db
from app.models import AdminUser


def _error(message, status):
    return jsonify({"ok": False, "error": message}), status


def current_user():
    """The logged-in AdminUser, or None. Re-checked in the database on every
    request, so disabling/deleting an account or changing its password logs
    that person out immediately."""
    if "_admin_user" in g:
        return g._admin_user
    user = None
    uid = session.get("uid")
    if uid:
        candidate = db.session.get(AdminUser, uid)
        if candidate and candidate.is_active and session.get("tv") == candidate.token_version:
            user = candidate
        else:
            session.clear()
    g._admin_user = user
    return user


def login_user(user):
    session.clear()  # new session on login (no session fixation)
    session["uid"] = user.id
    session["tv"] = user.token_version
    session["csrf"] = secrets.token_urlsafe(32)
    session.permanent = True
    g._admin_user = user


def logout_user():
    session.clear()
    g._admin_user = None


def csrf_token():
    return session.get("csrf", "")


def _csrf_ok():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    sent = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf", "")
    return bool(expected) and hmac.compare_digest(sent, expected)


def check_admin(owner_only=False):
    """None when allowed, otherwise the error response to return."""
    user = current_user()
    if user is None:
        return _error("Трябва да влезете в админ панела.", 401)
    if not _csrf_ok():
        return _error("Невалидна заявка (CSRF). Презаредете страницата.", 403)
    if owner_only and not user.is_owner:
        return _error("Нямате права за тази операция.", 403)
    return None


def admin_required(view):
    """Logged-in owner or coach."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        denied = check_admin()
        return denied if denied is not None else view(*args, **kwargs)
    return wrapper


def owner_required(view):
    """Main administrator only."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        denied = check_admin(owner_only=True)
        return denied if denied is not None else view(*args, **kwargs)
    return wrapper
