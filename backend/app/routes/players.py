"""Футболисти (админ): профили на деца + родителски акаунти.

  GET    /api/admin/players                       списък (?q=, ?team=, ?status=, ?archived=1)
  GET    /api/admin/players/<id>
  POST   /api/admin/players                       нов профил (+ родителски акаунт и имейл)
  PATCH  /api/admin/players/<id>                  редакция
  POST   /api/admin/players/<id>/new-password     нова временна парола на родителя (+ имейл)
  POST   /api/admin/players/<id>/archive|restore
  DELETE /api/admin/players/<id>                  архивира; ?forever=1 — истинско изтриване (само главен админ, само архивиран)
  GET    /api/admin/registrations/<id>/prefill    данни от запитването за формата „Създай профил“

Права: главен админ и главен треньор създават/редактират. Обикновен треньор вижда САМО играчите
на отборите си (от профила му), само за четене, без родителски данни, бележки и такси."""
from datetime import date

from flask import Blueprint, jsonify, request

from app import db
from app.auth import check_admin, current_user
from app.mailer import (
    MailError, build_parent_child_added_email, build_parent_new_password_email,
    build_parent_welcome_email, send_email,
)
from app.models import (
    PLAYER_ACTIVE, PLAYER_STATUSES, ParentAccount, Player, Registration, Team,
)
from app.player_utils import (
    EMAIL_RE, generate_temp_password, parse_date, player_dict, player_team,
)
from app.routes.news import _absolute
from app.team_utils import get_season_end_year, season_text, sort_key, u_label

admin_players_bp = Blueprint("admin_players", __name__)
admin_players_bp.before_request(check_admin)

TEMP_PASSWORD_DAYS = 7
MAX_NOTES = 2000


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _who():
    user = current_user()
    return (user.display_name or user.username)[:80] if user else ""


def _is_manager(user):
    return user.is_owner or user.is_head_coach


def _manager_only():
    """Грешка 403 за обикновен треньор, иначе None."""
    if not _is_manager(current_user()):
        return _error("Нямате права за тази операция.", 403)
    return None


def _coach_team_ids(user):
    profile = user.profile
    return {t.id for t in profile.teams} if profile is not None else set()


def _visible(player, user):
    if _is_manager(user):
        return True
    team, _manual = player_team(player)
    return team is not None and team.id in _coach_team_ids(user)


def _login_url():
    return _absolute("/parent-login.html")


def _send(to_addr, subject, body):
    """'sent' | 'dry_run' (няма MAIL_SERVER) | 'failed'."""
    try:
        return "sent" if send_email(to_addr, subject, body) else "dry_run"
    except MailError:
        return "failed"


def _text(value, limit, label, errors, key, required=False):
    text = " ".join(value.split()) if isinstance(value, str) else ("" if value is None else None)
    if text is None:
        errors[key] = "Невалидна стойност."
        return ""
    if required and not text:
        errors[key] = f"Въведете {label}."
    elif len(text) > limit:
        errors[key] = f"{label}: най-много {limit} символа."
    return text


def _date_field(data, key, errors, required=False):
    raw = data.get(key)
    if raw in (None, ""):
        if required:
            errors[key] = "Въведете дата."
        return None
    try:
        return parse_date(raw)
    except ValueError:
        errors[key] = "Невалидна дата."
        return None


def _team_override(data, errors):
    """(зададен?, team_id или None). Празна стойност = връща автоматичния отбор."""
    if "team_override_id" not in data:
        return False, None
    raw = data["team_override_id"]
    if raw in (None, ""):
        return True, None
    if isinstance(raw, bool) or not str(raw).isdigit() or db.session.get(Team, int(raw)) is None:
        errors["team_override_id"] = "Невалиден отбор."
        return False, None
    return True, int(raw)


def _notes(data, errors):
    if "internal_notes" not in data:
        return None
    value = data["internal_notes"]
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MAX_NOTES:
        errors["internal_notes"] = f"Бележките са до {MAX_NOTES} символа."
        return None
    return value.strip()


# ------------------------------------------------------------------ списък ---
@admin_players_bp.get("/admin/players")
def list_players():
    user = current_user()
    season_end = get_season_end_year()
    manager = _is_manager(user)
    show_archived = request.args.get("archived") == "1"
    query = Player.query.filter_by(archived=show_archived)
    status = request.args.get("status")
    if status in PLAYER_STATUSES:
        query = query.filter_by(status=status)
    players = [p for p in query.all() if _visible(p, user)]

    team_filter = request.args.get("team")
    if team_filter and team_filter.isdigit():
        players = [p for p in players if (player_team(p)[0] or Team()).id == int(team_filter)]
    needle = (request.args.get("q") or "").strip().casefold()
    if needle:
        players = [p for p in players if needle in p.child_name.casefold()
                   or (manager and (needle in p.parent.display_name.casefold() or needle in p.parent.email))]
    players.sort(key=lambda p: (sort_key(player_team(p)[0]) if player_team(p)[0] else (2, 0), p.child_name.casefold()))

    teams = sorted(Team.query.filter_by(status="active").all(), key=sort_key)
    return jsonify({
        "ok": True,
        "season": season_text(season_end),
        "can_edit": manager,
        "players": [player_dict(p, season_end, manager=manager) for p in players],
        "teams": [{"id": t.id, "label": u_label(t, season_end)} for t in teams],
    })


@admin_players_bp.get("/admin/players/<int:player_id>")
def get_player(player_id):
    user = current_user()
    player = db.session.get(Player, player_id)
    if player is None or not _visible(player, user):
        return _error("Профилът не е намерен.", 404)
    return jsonify({"ok": True, "player": player_dict(player, get_season_end_year(), manager=_is_manager(user))})


# ----------------------------------------------------------------- създаване ---
@admin_players_bp.post("/admin/players")
def create_player():
    denied = _manager_only()
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")

    errors = {}
    child_name = _text(data.get("child_name"), 120, "име на детето", errors, "child_name", required=True)
    birth_date = _date_field(data, "birth_date", errors, required=True)
    if birth_date and birth_date > date.today():
        errors["birth_date"] = "Датата на раждане е в бъдещето."
    start_date = _date_field(data, "start_date", errors)
    email = str(data.get("parent_email") or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 120:
        errors["parent_email"] = "Въведете валиден имейл на родителя."
    notes = _notes(data, errors)
    has_override, override_id = _team_override(data, errors)

    parent = ParentAccount.query.filter_by(email=email).first() if "parent_email" not in errors else None
    parent_name = _text(data.get("parent_name"), 120, "име на родител", errors, "parent_name", required=parent is None)
    parent_phone = _text(data.get("parent_phone"), 40, "телефон", errors, "parent_phone", required=parent is None)

    registration = None
    if data.get("registration_id") not in (None, ""):
        reg_id = data["registration_id"]
        registration = db.session.get(Registration, reg_id) if isinstance(reg_id, int) and not isinstance(reg_id, bool) else None
        if registration is None:
            errors["registration_id"] = "Запитването не е намерено."
        elif registration.player_id:
            errors["registration_id"] = "За това запитване вече има създаден профил."

    if not errors and parent is not None:
        for other in parent.players:
            if other.child_name.casefold() == child_name.casefold() and other.birth_date == birth_date:
                errors["child_name"] = "Това дете вече има профил в този родителски акаунт."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    existing_parent = parent is not None
    password = None
    if parent is None:
        parent = ParentAccount(email=email, display_name=parent_name, phone=parent_phone, password_hash="")
        password = generate_temp_password()
        parent.set_password(password, temporary=True, valid_days=TEMP_PASSWORD_DAYS)
        db.session.add(parent)
    elif not parent.is_active:
        # Върнат след архивиране на всички деца: нова временна парола, както при нов акаунт.
        password = generate_temp_password()
        parent.set_password(password, temporary=True, valid_days=TEMP_PASSWORD_DAYS)
        parent.is_active = True
        existing_parent = False

    player = Player(
        parent=parent, child_name=child_name, birth_date=birth_date, start_date=start_date or date.today(),
        internal_notes=notes or "", team_override_id=override_id if has_override else None,
        registration_id=registration.id if registration else None,
        created_by=_who(), updated_by=_who(),
    )
    db.session.add(player)
    db.session.flush()
    if registration is not None:
        registration.player_id = player.id
    db.session.commit()

    if password is not None:
        subject, body = build_parent_welcome_email(parent, child_name, password, _login_url())
    else:
        subject, body = build_parent_child_added_email(parent, child_name, _login_url())
    email_status = _send(parent.email, subject, body)

    season_end = get_season_end_year()
    return jsonify({
        "ok": True,
        "player": player_dict(player, season_end, manager=True),
        "parent_existing": existing_parent,
        "email_status": email_status,
    }), 201


# ------------------------------------------------------------------ редакция ---
@admin_players_bp.patch("/admin/players/<int:player_id>")
def update_player(player_id):
    denied = _manager_only()
    if denied:
        return denied
    player = db.session.get(Player, player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")

    errors = {}
    if "child_name" in data:
        name = _text(data["child_name"], 120, "име на детето", errors, "child_name", required=True)
        if "child_name" not in errors:
            player.child_name = name
    if "birth_date" in data:
        born = _date_field(data, "birth_date", errors, required=True)
        if born and born > date.today():
            errors["birth_date"] = "Датата на раждане е в бъдещето."
        elif born:
            player.birth_date = born
    if "start_date" in data:
        start = _date_field(data, "start_date", errors)
        if "start_date" not in errors:
            player.start_date = start
    if "status" in data:
        if data["status"] not in PLAYER_STATUSES:
            errors["status"] = "Невалиден статус."
        else:
            player.status = data["status"]
    notes = _notes(data, errors)
    if notes is not None:
        player.internal_notes = notes
    has_override, override_id = _team_override(data, errors)
    if has_override:
        player.team_override_id = override_id
    # Контактите на родителя са общи за всички негови деца. Имейлът (потребителското име) не се сменя оттук.
    if "parent_name" in data:
        value = _text(data["parent_name"], 120, "име на родител", errors, "parent_name", required=True)
        if "parent_name" not in errors:
            player.parent.display_name = value
    if "parent_phone" in data:
        value = _text(data["parent_phone"], 40, "телефон", errors, "parent_phone", required=True)
        if "parent_phone" not in errors:
            player.parent.phone = value

    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400
    player.updated_by = _who()
    db.session.commit()
    return jsonify({"ok": True, "player": player_dict(player, get_season_end_year(), manager=True)})


# ------------------------------------------------------------ нова парола ---
@admin_players_bp.post("/admin/players/<int:player_id>/new-password")
def new_password(player_id):
    """Нова временна парола. Старата спира веднага, новата изисква смяна. Паролата
    се праща по имейл и треньорът не я вижда."""
    denied = _manager_only()
    if denied:
        return denied
    player = db.session.get(Player, player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    parent = player.parent
    never_logged_in = parent.last_login_at is None

    password = generate_temp_password()
    parent.set_password(password, temporary=True, valid_days=TEMP_PASSWORD_DAYS)  # token_version +1
    parent.failed_attempts = 0
    parent.locked_until = None
    parent.is_active = True
    db.session.commit()

    if never_logged_in:
        subject, body = build_parent_welcome_email(parent, player.child_name, password, _login_url())
    else:
        subject, body = build_parent_new_password_email(parent, password, _login_url())
    return jsonify({"ok": True, "email_status": _send(parent.email, subject, body)})


# --------------------------------------------------------------- архив / изтриване ---
def _sync_parent_access(parent):
    """Родител без нито едно активно дете няма достъп; с активно дете — има."""
    has_active = any(not p.archived for p in parent.players)
    parent.is_active = has_active
    if not has_active:
        parent.token_version += 1  # прекратява отворената му сесия


@admin_players_bp.post("/admin/players/<int:player_id>/archive")
def archive_player(player_id):
    denied = _manager_only()
    if denied:
        return denied
    player = db.session.get(Player, player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    player.archived = True
    player.updated_by = _who()
    db.session.flush()
    _sync_parent_access(player.parent)
    db.session.commit()
    return jsonify({"ok": True, "player": player_dict(player, get_season_end_year(), manager=True)})


@admin_players_bp.post("/admin/players/<int:player_id>/restore")
def restore_player(player_id):
    denied = _manager_only()
    if denied:
        return denied
    player = db.session.get(Player, player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    player.archived = False
    player.updated_by = _who()
    db.session.flush()
    parent = player.parent
    if not parent.is_active:
        # Достъпът се връща със същата парола; ако не помни — „Нова временна парола“.
        parent.is_active = True
    db.session.commit()
    return jsonify({"ok": True, "player": player_dict(player, get_season_end_year(), manager=True)})


@admin_players_bp.delete("/admin/players/<int:player_id>")
def delete_player(player_id):
    """Без ?forever=1 само архивира. Истинско изтриване — само главен админ и само за архивиран профил."""
    if request.args.get("forever") != "1":
        return archive_player(player_id)
    user = current_user()
    if not user.is_owner:
        return _error("Истинско изтриване прави само главният администратор.", 403)
    player = db.session.get(Player, player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    if not player.archived:
        return _error("Първо архивирайте профила.", 409)
    parent = player.parent
    for registration in Registration.query.filter_by(player_id=player.id).all():
        registration.player_id = None
    db.session.delete(player)
    db.session.flush()
    if not parent.players:
        db.session.delete(parent)
    db.session.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------ данни от запитване ---
@admin_players_bp.get("/admin/registrations/<int:registration_id>/prefill")
def prefill(registration_id):
    denied = _manager_only()
    if denied:
        return denied
    registration = db.session.get(Registration, registration_id)
    if registration is None:
        return _error("Запитването не е намерено.", 404)
    return jsonify({
        "ok": True,
        "registration_id": registration.id,
        "already_created": registration.player_id,
        "child_name": registration.child_name,
        "child_age": registration.child_age,
        "parent_name": registration.parent_name,
        "parent_phone": registration.phone,
        "parent_email": registration.email,
    })
