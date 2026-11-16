"""Известия към родителите (админ): главният треньор пише известие за всички, за отбор или за дете.

  GET    /api/admin/announcements          списък със състояние и брой получатели
  POST   /api/admin/announcements          ново известие
  PATCH  /api/admin/announcements/<id>     промяна (вкл. скриване)
  DELETE /api/admin/announcements/<id>     изтриване

Само в портала (без имейл). Показва се от датата на публикуване до последния ден (включително), ако има такъв.
Текстът е обикновен текст — не се приема HTML; порталът го показва като текст."""
from datetime import date

from flask import Blueprint, current_app, jsonify, request

from app import db
from app.announcement_utils import (
    STATE_LABELS, audience_text, children_for, date_text, recipients, state, today,
)
from app.auth import check_admin, current_user
from app.mailer import MailError, build_announcement_email, send_email
from app.models import AUD_ALL, AUD_PLAYER, AUD_TEAM, AUDIENCES, Announcement, Player, Team, utcnow
from app.routes.news import _absolute
from app.routes.players import _manager_only, _who
from app.team_utils import get_season_end_year, sort_key, u_label

admin_announcements_bp = Blueprint("admin_announcements", __name__)
admin_announcements_bp.before_request(check_admin)

MAX_TITLE = 120
MAX_BODY = 2000


@admin_announcements_bp.before_request
def _managers_only():
    return _manager_only() if current_user() is not None else None


def _error(message, status=400, errors=None):
    body = {"ok": False, "error": message}
    if errors:
        body["errors"] = errors
    return jsonify({**body}), status


def _iso(value):
    return value.isoformat() if value else None


def announcement_dict(a):
    st = state(a)
    return {
        "id": a.id, "title": a.title, "body": a.body,
        "audience": a.audience, "audience_text": audience_text(a), "team_id": a.team_id, "player_id": a.player_id,
        "publish_date": _iso(a.publish_date), "publish_text": date_text(a.publish_date),
        "expires_date": _iso(a.expires_date), "expires_text": date_text(a.expires_date) if a.expires_date else "",
        "is_hidden": bool(a.is_hidden), "state": st, "state_label": STATE_LABELS[st],
        "recipients": recipients(a), "created_by": a.created_by, "updated_by": a.updated_by,
        "emailed_at": _iso(a.emailed_at), "emailed_count": a.emailed_count or 0,
        "can_email": st == "active",
    }


def _parse_date(value):
    if not isinstance(value, str):
        raise ValueError
    return date.fromisoformat(value.strip()[:10])


def _apply(a, data, creating):
    errors = {}
    if creating or "title" in data:
        title = " ".join(data["title"].split()) if isinstance(data.get("title"), str) else ""
        if not title:
            errors["title"] = "Въведете заглавие."
        elif len(title) > MAX_TITLE:
            errors["title"] = f"Заглавието е до {MAX_TITLE} символа."
        else:
            a.title = title
    if creating or "body" in data:
        body = data.get("body")
        body = "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").strip().split("\n")) if isinstance(body, str) else ""
        if not body:
            errors["body"] = "Напишете текста на известието."
        elif len(body) > MAX_BODY:
            errors["body"] = f"Текстът е до {MAX_BODY} символа."
        else:
            a.body = body
    if creating or {"audience", "team_id", "player_id"} & set(data):
        audience = data.get("audience", a.audience if not creating else AUD_ALL)
        if audience not in AUDIENCES:
            errors["audience"] = "Изберете за кого е известието."
        elif audience == AUD_ALL:
            a.audience, a.team_id, a.player_id = AUD_ALL, None, None
        elif audience == AUD_TEAM:
            team = db.session.get(Team, data.get("team_id") if isinstance(data.get("team_id"), int) else 0)
            if team is None or team.status != "active":
                errors["team_id"] = "Изберете активен отбор."
            else:
                a.audience, a.team_id, a.player_id = AUD_TEAM, team.id, None
        else:
            player = db.session.get(Player, data.get("player_id") if isinstance(data.get("player_id"), int) else 0)
            if player is None or player.archived:
                errors["player_id"] = "Изберете дете."
            else:
                a.audience, a.team_id, a.player_id = AUD_PLAYER, None, player.id
    if creating or "publish_date" in data:
        try:
            a.publish_date = _parse_date(data["publish_date"]) if data.get("publish_date") else today()
        except ValueError:
            errors["publish_date"] = "Невалидна дата."
    if "expires_date" in data or creating:
        raw = data.get("expires_date")
        if raw in (None, ""):
            a.expires_date = None
        else:
            try:
                a.expires_date = _parse_date(raw)
            except ValueError:
                errors["expires_date"] = "Невалидна дата."
    if "publish_date" not in errors and "expires_date" not in errors and a.expires_date and a.publish_date \
            and a.expires_date < a.publish_date:
        errors["expires_date"] = "Крайната дата не може да е преди началото."
    if "is_hidden" in data:
        if not isinstance(data["is_hidden"], bool):
            errors["is_hidden"] = "Невалидна стойност."
        else:
            a.is_hidden = data["is_hidden"]
    return errors


@admin_announcements_bp.get("/admin/announcements")
def list_announcements():
    items = Announcement.query.order_by(Announcement.publish_date.desc(), Announcement.id.desc()).all()
    season_end = get_season_end_year()
    teams = sorted(Team.query.filter_by(status="active").all(), key=sort_key)
    return jsonify({
        "ok": True,
        "announcements": [announcement_dict(a) for a in items],
        "teams": [{"id": t.id, "label": u_label(t, season_end)} for t in teams],
        "today": today().isoformat(),
        "mail_configured": bool(current_app.config.get("MAIL_SERVER")),
    })


@admin_announcements_bp.post("/admin/announcements")
def create_announcement():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    a = Announcement()
    errors = _apply(a, data, creating=True)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    a.created_by = a.updated_by = _who()
    db.session.add(a)
    db.session.commit()
    return jsonify({"ok": True, "announcement": announcement_dict(a)}), 201


@admin_announcements_bp.patch("/admin/announcements/<int:announcement_id>")
def update_announcement(announcement_id):
    a = db.session.get(Announcement, announcement_id)
    if a is None:
        return _error("Известието не е намерено.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    errors = _apply(a, data, creating=False)
    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400
    a.updated_by = _who()
    db.session.commit()
    return jsonify({"ok": True, "announcement": announcement_dict(a)})


@admin_announcements_bp.delete("/admin/announcements/<int:announcement_id>")
def delete_announcement(announcement_id):
    a = db.session.get(Announcement, announcement_id)
    if a is None:
        return _error("Известието не е намерено.", 404)
    db.session.delete(a)
    db.session.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------ изпращане по имейл ---
MAX_EMAIL_RECIPIENTS = 300


def _email_targets(announcement):
    """[(родител, [имена на деца, за които важи])] — родителите, които получават известието."""
    by_parent = {}
    for player in Player.query.filter_by(archived=False).order_by(Player.child_name).all():
        if children_for(announcement, [player]):
            by_parent.setdefault(player.parent_id, (player.parent, []))[1].append(player.child_name)
    return list(by_parent.values())


@admin_announcements_bp.post("/admin/announcements/<int:announcement_id>/send-email")
def send_announcement_email(announcement_id):
    """Изпраща известието по имейл на родителите, които го получават. Само за известие, което се показва в
    портала сега. Без настроен MAIL_SERVER (тестов режим) имейлите само се записват в лога и не се броят за изпратени.
    Изпращането е последователно, в самата заявка — при голям брой получатели ще се прехвърли на опашка."""
    a = db.session.get(Announcement, announcement_id)
    if a is None:
        return _error("Известието не е намерено.", 404)
    if state(a) != "active":
        return _error("По имейл се изпраща само известие, което се показва в портала в момента.", 409)
    targets = _email_targets(a)
    if not targets:
        return _error("Няма родители, които да получат известието.", 409)
    if len(targets) > MAX_EMAIL_RECIPIENTS:
        return _error(f"Твърде много получатели за наведнъж (над {MAX_EMAIL_RECIPIENTS}).", 409)

    portal_url = _absolute("/parent-login.html")
    sent = dry = 0
    failed = []
    for parent, names in targets:
        children = [] if a.audience == AUD_ALL else names
        subject, body = build_announcement_email(parent, a, children, portal_url)
        try:
            if send_email(parent.email, subject, body):
                sent += 1
            else:
                dry += 1  # няма MAIL_SERVER: записано в лога, не е изпратено реално
        except MailError:
            current_app.logger.warning("Известие %s: имейлът до родител %s не можа да бъде изпратен.", a.id, parent.id)
            failed.append(parent.email)
    if sent:
        a.emailed_at = utcnow()
        a.emailed_count = sent
        a.updated_by = _who()
        db.session.commit()
    return jsonify({
        "ok": True, "total": len(targets), "sent": sent, "dry_run": dry, "failed": len(failed), "failed_emails": failed,
        "announcement": announcement_dict(a),
    })
