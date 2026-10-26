"""Тренировъчен график: публична страница /schedule + админ API.

Админ:  GET    /api/admin/schedule        слотове + списък с отбори
        POST   /api/admin/schedule        нов слот (или няколко — по един на ден)
        PATCH  /api/admin/schedule/<id>   промяна на слот
        DELETE /api/admin/schedule/<id>   изтриване на слот
"""
import re

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy.orm import selectinload

from app import db
from app.auth import check_admin
from app.models import TEAM_ACTIVE, Team, TrainingSlot
from app.routes.news import DEFAULT_SHARE_IMAGE, _absolute
from app.routes.teams import admin_dict
from app.schedule_utils import DAY_NAMES, build_public_schedule, day_name, slot_label
from app.team_utils import get_season_end_year, sort_key

page_bp = Blueprint("schedule_page", __name__)
admin_schedule_bp = Blueprint("admin_schedule", __name__)
admin_schedule_bp.before_request(check_admin)  # собственик или треньор

MAX_LABEL = 40
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


@page_bp.get("/schedule")
@page_bp.get("/schedule/")
def schedule_page():
    return render_template(
        "schedule_page.html",
        schedule=build_public_schedule(),
        page_url=_absolute("/schedule"),
        image_url=_absolute(DEFAULT_SHARE_IMAGE),
    )


# ------------------------------------------------------------------ admin ---
def _slot_dict(slot):
    teams = sorted(slot.teams, key=sort_key)
    if teams:
        shown = slot_label(teams)
        visible = any(t.status == TEAM_ACTIVE for t in teams)
    else:
        shown = slot.label
        visible = bool(slot.label)
    return {
        "id": slot.id,
        "day": slot.weekday,
        "day_name": day_name(slot.weekday),
        "time": slot.start_time,
        "label": slot.label,      # свободният текст
        "shown": shown,           # какво се вижда на сайта
        "team_ids": [t.id for t in teams],
        "visible": visible,
    }


def _normalize_time(value):
    if not isinstance(value, str):
        return None
    match = TIME_RE.match(value.strip())
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else None


def _parse_team_ids(value):
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError
    ids = []
    for item in value:
        if isinstance(item, bool) or not str(item).strip().isdigit():
            raise ValueError
        ids.append(int(item))
    return list(dict.fromkeys(ids))  # без повторения, в същия ред


def _team_key(slot_or_ids):
    return tuple(sorted(slot_or_ids))


def _duplicate(day, time, team_ids, label, ignore_id=None):
    query = TrainingSlot.query.options(selectinload(TrainingSlot.teams)).filter_by(weekday=day, start_time=time)
    for other in query.all():
        if ignore_id is not None and other.id == ignore_id:
            continue
        if team_ids:
            if _team_key(t.id for t in other.teams) == _team_key(team_ids):
                return True
        elif not other.teams and other.label.casefold() == label.casefold():
            return True
    return False


def _validate(data, days):
    """Връща (cleaned, errors). days — списък дни, за които се прилага."""
    errors = {}
    cleaned = {}

    time = _normalize_time(data.get("time"))
    if time is None:
        errors["time"] = "Въведете час, например 18:30."
    cleaned["time"] = time

    try:
        team_ids = _parse_team_ids(data.get("team_ids"))
    except ValueError:
        team_ids = []
        errors["team_ids"] = "Невалиден избор на отбори."
    if team_ids and "team_ids" not in errors:
        found = Team.query.filter(Team.id.in_(team_ids)).all()
        if len(found) != len(team_ids):
            errors["team_ids"] = "Някой от избраните отбори не съществува."
        cleaned["teams"] = sorted(found, key=lambda t: team_ids.index(t.id))
    else:
        cleaned["teams"] = []

    label = data.get("label", "")
    if label is not None and not isinstance(label, str):
        errors["label"] = "Невалидна стойност."
        label = ""
    label = (label or "").strip()
    if len(label) > MAX_LABEL:
        errors["label"] = f"Максимум {MAX_LABEL} символа."
    if not team_ids and not label and "team_ids" not in errors and "label" not in errors:
        errors["team_ids"] = "Изберете поне един отбор или въведете текст (напр. „Вратари — големи“)."
    cleaned["label"] = "" if team_ids else label  # свободният текст важи само без отбори

    if not days:
        errors["days"] = "Изберете поне един ден."
    for day in days:
        if not isinstance(day, int) or not 1 <= day <= 7:
            errors["days"] = "Невалиден ден."
            break
    cleaned["days"] = days
    return cleaned, errors


@admin_schedule_bp.get("/admin/schedule")
def admin_list():
    slots = (
        TrainingSlot.query.options(selectinload(TrainingSlot.teams))
        .order_by(TrainingSlot.weekday, TrainingSlot.start_time, TrainingSlot.id)
        .all()
    )
    season_end = get_season_end_year()
    teams = sorted(Team.query.all(), key=sort_key)
    team_dicts = [admin_dict(t, season_end) for t in teams]
    names = {t["id"]: t["u_label"] for t in team_dicts}
    slot_dicts = []
    for slot in slots:
        d = _slot_dict(slot)
        d["team_names"] = [names.get(i, "?") for i in d["team_ids"]]
        slot_dicts.append(d)
    return jsonify({
        "ok": True,
        "days": [{"number": i + 1, "name": n} for i, n in enumerate(DAY_NAMES)],
        "teams": [
            {"id": t["id"], "u_label": t["u_label"], "cohort": t["cohort"], "kind": t["kind"], "status": t["status"]}
            for t in team_dicts
        ],
        "slots": slot_dicts,
    })


def _respond_slots(slots, status=200):
    return jsonify({"ok": True, "slots": [_slot_dict(s) for s in slots]}), status


@admin_schedule_bp.post("/admin/schedule")
def admin_create():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    days = data.get("days", [data["day"]] if "day" in data else [])
    if not isinstance(days, list):
        return _error("Невалидна заявка.")
    days = list(dict.fromkeys(days))

    cleaned, errors = _validate(data, days)
    if not errors:
        team_ids = [t.id for t in cleaned["teams"]]
        clashes = [day_name(d) for d in days if _duplicate(d, cleaned["time"], team_ids, cleaned["label"])]
        if clashes:
            errors["days"] = "Вече има такъв слот: " + ", ".join(clashes) + "."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    created = []
    for day in days:
        slot = TrainingSlot(weekday=day, start_time=cleaned["time"], label=cleaned["label"])
        slot.teams = list(cleaned["teams"])
        db.session.add(slot)
        created.append(slot)
    db.session.commit()
    return _respond_slots(created, 201)


@admin_schedule_bp.patch("/admin/schedule/<int:slot_id>")
def admin_update(slot_id):
    slot = db.session.get(TrainingSlot, slot_id)
    if slot is None:
        return _error("Слотът не е намерен.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    day = data.get("day", slot.weekday)

    cleaned, errors = _validate(data, [day])
    if not errors:
        team_ids = [t.id for t in cleaned["teams"]]
        if _duplicate(day, cleaned["time"], team_ids, cleaned["label"], ignore_id=slot.id):
            errors["days"] = "Вече има такъв слот."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    slot.weekday = day
    slot.start_time = cleaned["time"]
    slot.label = cleaned["label"]
    slot.teams = list(cleaned["teams"])
    db.session.commit()
    return _respond_slots([slot])


@admin_schedule_bp.delete("/admin/schedule/<int:slot_id>")
def admin_delete(slot_id):
    slot = db.session.get(TrainingSlot, slot_id)
    if slot is None:
        return _error("Слотът не е намерен.", 404)
    db.session.delete(slot)
    db.session.commit()
    return jsonify({"ok": True})
