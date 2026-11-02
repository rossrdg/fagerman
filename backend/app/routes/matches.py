"""Мачове от първенствата: публична страница /matches (седмичен афиш) + админ API.

Публично: GET /matches[?week=ГГГГ-ММ-ДД]  афиш за седмицата; без параметър — най-близката седмица с мачове
          (мачовете на отбора са и на страницата му /teams/<адрес>)

Админ:  GET    /api/admin/matches?team=<id>&season=<година>   мачове + отбори + сезони + подсказки
        POST   /api/admin/matches                             нов мач / почивен кръг
        PATCH  /api/admin/matches/<id>                        промяна (или само резултат)
        DELETE /api/admin/matches/<id>                        изтриване (всеки влязъл потребител)

Всички влезли потребители (собственик, главен треньор, треньор) могат да добавят, променят
и трият мачове — както при графика.
"""
import re
from datetime import date, time

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func

from app import db
from app.auth import check_admin, current_user
from app.match_utils import build_week, match_dict, sort_matches
from app.models import (
    MATCH_NOT_PLAYED, MATCH_PLAYED, MATCH_POSTPONED, MATCH_REST, MATCH_SCHEDULED, MATCH_STATUSES,
    TEAM_ACTIVE, Match, Team,
)
from app.routes.news import DEFAULT_SHARE_IMAGE, _absolute
from app.routes.teams import admin_dict
from app.team_utils import get_season_end_year, season_text, sort_key

page_bp = Blueprint("matches_page", __name__)
admin_matches_bp = Blueprint("admin_matches", __name__)
admin_matches_bp.before_request(check_admin)

MAX_OPPONENT = 80
MAX_VENUE = 120
MAX_NOTE = 200
MAX_GOALS = 99
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
FIELDS = ("round_no", "date", "time", "is_home", "opponent", "venue", "status",
          "goals_for", "goals_against", "note")


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _who():
    user = current_user()
    return (user.display_name or user.username) if user else ""


def _int_or_none(value):
    """Цяло число от JSON (приема и текст като „3“). None при празно; ValueError при грешка."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r"\d{1,4}", value):
            raise ValueError
    return int(value)


def _current_values(match):
    return {
        "round_no": match.round_no,
        "date": match.match_date.isoformat() if match.match_date else None,
        "time": match.match_time.strftime("%H:%M") if match.match_time else None,
        "is_home": bool(match.is_home),
        "opponent": match.opponent,
        "venue": match.venue,
        "status": match.status,
        "goals_for": match.goals_for,
        "goals_against": match.goals_against,
        "note": match.note,
    }


def _text(value, limit, label, errors, key):
    text = value.strip() if isinstance(value, str) else ("" if value is None else None)
    if text is None:
        errors[key] = "Невалидна стойност."
        return ""
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        errors[key] = f"{label}: най-много {limit} символа."
    return text


def validate(values, team_id, season_end, ignore_id=None):
    """Проверява пълния набор стойности. Връща (cleaned, errors)."""
    errors = {}
    c = {}

    status = values.get("status") or MATCH_SCHEDULED
    if status not in MATCH_STATUSES:
        errors["status"] = "Невалиден статус."
        status = MATCH_SCHEDULED
    rest = status == MATCH_REST

    try:
        c["round_no"] = _int_or_none(values.get("round_no"))
        if c["round_no"] is not None and not 1 <= c["round_no"] <= 99:
            raise ValueError
    except ValueError:
        c["round_no"] = None
        errors["round_no"] = "Кръгът е число от 1 до 99."
    if rest and c["round_no"] is None and "round_no" not in errors:
        errors["round_no"] = "Почивният кръг трябва да има номер."

    c["match_date"] = None
    raw_date = values.get("date")
    if raw_date not in (None, ""):
        try:
            c["match_date"] = date.fromisoformat(str(raw_date))
            if not 2000 <= c["match_date"].year <= 2100:
                raise ValueError
        except ValueError:
            errors["date"] = "Невалидна дата."
    elif status not in (MATCH_POSTPONED, MATCH_NOT_PLAYED):
        errors["date"] = "Въведете дата."

    c["match_time"] = None
    raw_time = values.get("time")
    if raw_time not in (None, "") and not rest:
        found = TIME_RE.match(str(raw_time).strip())
        if found:
            c["match_time"] = time(int(found.group(1)), int(found.group(2)))
        else:
            errors["time"] = "Въведете час, например 10:30."

    is_home = values.get("is_home", True)
    if not isinstance(is_home, bool):
        errors["is_home"] = "Изберете домакин или гост."
        is_home = True
    c["is_home"] = True if rest else is_home

    c["opponent"] = _text(values.get("opponent"), MAX_OPPONENT, "Съперник", errors, "opponent")
    if rest:
        c["opponent"] = ""
    elif not c["opponent"] and "opponent" not in errors:
        errors["opponent"] = "Въведете съперник."
    c["venue"] = "" if rest else _text(values.get("venue"), MAX_VENUE, "Място", errors, "venue")
    c["note"] = _text(values.get("note"), MAX_NOTE, "Бележка", errors, "note")

    goals = {}
    for key in ("goals_for", "goals_against"):
        try:
            goals[key] = _int_or_none(values.get(key))
            if goals[key] is not None and not 0 <= goals[key] <= MAX_GOALS:
                raise ValueError
        except ValueError:
            goals[key] = None
            errors[key] = f"Голове: число от 0 до {MAX_GOALS}."
    has_for, has_against = goals["goals_for"] is not None, goals["goals_against"] is not None
    if not ({"goals_for", "goals_against"} & set(errors)):
        if has_for != has_against:
            errors["goals_for"] = "Въведете головете и на двата отбора."
        elif has_for and status in (MATCH_POSTPONED, MATCH_NOT_PLAYED, MATCH_REST):
            errors["status"] = "Резултат може да има само изигран мач."
        elif has_for and status == MATCH_SCHEDULED:
            status = MATCH_PLAYED  # въведен резултат = изигран мач
        elif not has_for and status == MATCH_PLAYED:
            errors["goals_for"] = "Изиграният мач трябва да има резултат."
    c["status"] = status
    c["goals_for"], c["goals_against"] = goals["goals_for"], goals["goals_against"]

    if not errors and c["round_no"] is not None:
        query = Match.query.filter_by(team_id=team_id, season_end=season_end, round_no=c["round_no"])
        for other in query.all():
            if other.id == ignore_id:
                continue
            if rest or other.status == MATCH_REST or other.opponent.casefold() == c["opponent"].casefold():
                errors["round_no"] = f"Кръг {c['round_no']} вече съществува за този отбор."
                break
    return c, errors


def _apply(match, c):
    match.round_no = c["round_no"]
    match.match_date = c["match_date"]
    match.match_time = c["match_time"]
    match.is_home = c["is_home"]
    match.opponent = c["opponent"]
    match.venue = c["venue"]
    match.status = c["status"]
    match.goals_for = c["goals_for"]
    match.goals_against = c["goals_against"]
    match.note = c["note"]


# ----------------------------------------------------------------- public ---
@page_bp.get("/matches")
@page_bp.get("/matches/")
def matches_page():
    season_end = get_season_end_year()
    return render_template(
        "matches_page.html",
        week=build_week(season_end, request.args.get("week")),
        season=season_text(season_end),
        page_url=_absolute("/matches"),
        image_url=_absolute(DEFAULT_SHARE_IMAGE),
    )


# ------------------------------------------------------------------ admin ---
@admin_matches_bp.get("/admin/matches")
def admin_list():
    current_season = get_season_end_year()
    try:
        season_end = _int_or_none(request.args.get("season")) or current_season
        team_id = _int_or_none(request.args.get("team"))
    except ValueError:
        return _error("Невалидна заявка.")

    teams = sorted(Team.query.all(), key=sort_key)
    team_dicts = [admin_dict(t, current_season) for t in teams]

    query = Match.query.filter_by(season_end=season_end)
    if team_id is not None:
        query = query.filter_by(team_id=team_id)
    matches = query.all()
    order = {t.id: i for i, t in enumerate(teams)}
    matches.sort(key=lambda m: order.get(m.team_id, 99))
    grouped = []
    for tid in dict.fromkeys(m.team_id for m in matches):
        grouped.extend(sort_matches([m for m in matches if m.team_id == tid]))

    seasons = {current_season}
    seasons.update(r[0] for r in db.session.query(Match.season_end).distinct().all())
    opponents = [r[0] for r in db.session.query(Match.opponent).filter(Match.opponent != "")
                 .group_by(Match.opponent).order_by(func.count().desc(), Match.opponent).limit(300)]
    venues = [r[0] for r in db.session.query(Match.venue).filter(Match.venue != "")
              .group_by(Match.venue).order_by(func.count().desc(), Match.venue).limit(100)]

    return jsonify({
        "ok": True,
        "season": season_end,
        "season_text": season_text(season_end),
        "current_season": current_season,
        "seasons": [{"end": s, "text": season_text(s)} for s in sorted(seasons, reverse=True)],
        "teams": [
            {"id": t["id"], "slug": t["slug"], "u_label": t["u_label"], "cohort": t["cohort"],
             "kind": t["kind"], "status": t["status"]}
            for t in team_dicts
        ],
        "matches": [match_dict(m) for m in grouped],
        "suggestions": {"opponents": opponents, "venues": venues},
    })


@admin_matches_bp.post("/admin/matches")
def admin_create():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    try:
        team_id = _int_or_none(data.get("team_id"))
        season_end = _int_or_none(data.get("season")) or get_season_end_year()
    except ValueError:
        return _error("Невалидна заявка.")
    team = db.session.get(Team, team_id) if team_id else None
    if team is None:
        return jsonify({"ok": False, "errors": {"team_id": "Изберете отбор."}}), 400
    if not 2000 <= season_end <= 2100:
        return _error("Невалиден сезон.")

    values = {key: data.get(key) for key in FIELDS if key in data}
    values.setdefault("is_home", True)
    cleaned, errors = validate(values, team.id, season_end)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    match = Match(team_id=team.id, season_end=season_end, created_by=_who(), updated_by=_who())
    _apply(match, cleaned)
    db.session.add(match)
    db.session.commit()
    return jsonify({"ok": True, "match": match_dict(match)}), 201


@admin_matches_bp.patch("/admin/matches/<int:match_id>")
def admin_update(match_id):
    match = db.session.get(Match, match_id)
    if match is None:
        return _error("Мачът не е намерен.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")

    values = _current_values(match)
    values.update({key: data[key] for key in FIELDS if key in data})
    # Само нови голове при мач, който още не е изигран -> става изигран (виж validate).
    cleaned, errors = validate(values, match.team_id, match.season_end, ignore_id=match.id)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    _apply(match, cleaned)
    match.updated_by = _who()
    db.session.commit()
    return jsonify({"ok": True, "match": match_dict(match)})


@admin_matches_bp.delete("/admin/matches/<int:match_id>")
def admin_delete(match_id):
    match = db.session.get(Match, match_id)
    if match is None:
        return _error("Мачът не е намерен.", 404)
    db.session.delete(match)
    db.session.commit()
    return jsonify({"ok": True})
