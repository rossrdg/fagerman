"""Тренировъчен график: публична страница /schedule + админ API.

Админ:  GET    /api/admin/schedule        слотове + списък с отбори
        POST   /api/admin/schedule        нов слот (или няколко — по един на ден)
        PATCH  /api/admin/schedule/<id>   промяна на слот
        DELETE /api/admin/schedule/<id>   изтриване на слот

Групи без отбор (напр. „Вратари — големи“) — избират се като отборите:
        POST   /api/admin/schedule-groups        нова група
        PATCH  /api/admin/schedule-groups/<id>   преименуване
        DELETE /api/admin/schedule-groups/<id>   изтриване (маха я от слотовете и профилите на треньорите)
"""
import re

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy.orm import selectinload

from app import db
from app.auth import check_admin
from app.models import TEAM_ACTIVE, Team, TrainingGroup, TrainingSlot
from app.routes.news import DEFAULT_SHARE_IMAGE, _absolute
from app.routes.teams import admin_dict
from app.schedule_utils import DAY_NAMES, build_public_schedule, day_name, find_group_by_name, slot_label
from app.team_utils import get_season_end_year, sort_key

page_bp = Blueprint("schedule_page", __name__)
admin_schedule_bp = Blueprint("admin_schedule", __name__)
admin_schedule_bp.before_request(check_admin)  # собственик или треньор

MAX_GROUP_NAME = 40
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
    groups = sorted(slot.groups, key=lambda g: g.name.casefold())
    if teams or groups:
        shown = slot_label(teams, groups)
        visible = bool(groups) or any(t.status == TEAM_ACTIVE for t in teams)
    else:
        shown = slot.label  # стар слот със свободен текст (преди групите)
        visible = bool(slot.label)
    return {
        "id": slot.id,
        "day": slot.weekday,
        "day_name": day_name(slot.weekday),
        "time": slot.start_time,
        "shown": shown,           # какво се вижда на сайта
        "team_ids": [t.id for t in teams],
        "group_ids": [g.id for g in groups],
        "group_names": [g.name for g in groups],
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


def _duplicate(day, time, team_ids, group_ids, ignore_id=None):
    query = (TrainingSlot.query.options(selectinload(TrainingSlot.teams), selectinload(TrainingSlot.groups))
             .filter_by(weekday=day, start_time=time))
    for other in query.all():
        if ignore_id is not None and other.id == ignore_id:
            continue
        if (sorted(t.id for t in other.teams) == sorted(team_ids)
                and sorted(g.id for g in other.groups) == sorted(group_ids)):
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
        group_ids = _parse_team_ids(data.get("group_ids"))
    except ValueError:
        team_ids, group_ids = [], []
        errors["team_ids"] = "Невалиден избор."
    cleaned["teams"], cleaned["groups"] = [], []
    if "team_ids" not in errors:
        if team_ids:
            found = Team.query.filter(Team.id.in_(team_ids)).all()
            if len(found) != len(team_ids):
                errors["team_ids"] = "Някой от избраните отбори не съществува."
            cleaned["teams"] = sorted(found, key=lambda t: team_ids.index(t.id))
        if group_ids:
            found = TrainingGroup.query.filter(TrainingGroup.id.in_(group_ids)).all()
            if len(found) != len(group_ids):
                errors["team_ids"] = "Някоя от избраните групи не съществува."
            cleaned["groups"] = sorted(found, key=lambda g: group_ids.index(g.id))
        if not team_ids and not group_ids:
            errors["team_ids"] = "Изберете поне един отбор или група (напр. вратари)."

    if not days:
        errors["days"] = "Изберете поне един ден."
    for day in days:
        if not isinstance(day, int) or not 1 <= day <= 7:
            errors["days"] = "Невалиден ден."
            break
    cleaned["days"] = days
    return cleaned, errors


def _group_dicts():
    groups = TrainingGroup.query.order_by(TrainingGroup.name).all()
    return [{"id": g.id, "name": g.name, "slots": len(g.training_slots), "coaches": len(g.coach_profiles)} for g in groups]


@admin_schedule_bp.get("/admin/schedule")
def admin_list():
    slots = (
        TrainingSlot.query.options(selectinload(TrainingSlot.teams), selectinload(TrainingSlot.groups))
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
        "groups": _group_dicts(),
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
        group_ids = [g.id for g in cleaned["groups"]]
        clashes = [day_name(d) for d in days if _duplicate(d, cleaned["time"], team_ids, group_ids)]
        if clashes:
            errors["days"] = "Вече има такъв слот: " + ", ".join(clashes) + "."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    created = []
    for day in days:
        slot = TrainingSlot(weekday=day, start_time=cleaned["time"], label="")
        slot.teams = list(cleaned["teams"])
        slot.groups = list(cleaned["groups"])
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
        group_ids = [g.id for g in cleaned["groups"]]
        if _duplicate(day, cleaned["time"], team_ids, group_ids, ignore_id=slot.id):
            errors["days"] = "Вече има такъв слот."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    slot.weekday = day
    slot.start_time = cleaned["time"]
    slot.label = ""
    slot.teams = list(cleaned["teams"])
    slot.groups = list(cleaned["groups"])
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


# ------------------------------------------------- групи без отбор (вратари) ---
def _group_name(data):
    name = data.get("name") if isinstance(data, dict) else None
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        return None, "Въведете име на групата."
    if len(name) > MAX_GROUP_NAME:
        return None, f"Максимум {MAX_GROUP_NAME} символа."
    return name, None


def _name_taken(name, ignore_id=None):
    return find_group_by_name(name, ignore_id=ignore_id) is not None


@admin_schedule_bp.post("/admin/schedule-groups")
def admin_create_group():
    name, error = _group_name(request.get_json(silent=True))
    if error is None and _name_taken(name):
        error = "Група с такова име вече има."
    if error:
        return jsonify({"ok": False, "errors": {"name": error}}), 400
    group = TrainingGroup(name=name)
    db.session.add(group)
    db.session.commit()
    return jsonify({"ok": True, "groups": _group_dicts()}), 201


@admin_schedule_bp.patch("/admin/schedule-groups/<int:group_id>")
def admin_rename_group(group_id):
    group = db.session.get(TrainingGroup, group_id)
    if group is None:
        return _error("Групата не е намерена.", 404)
    name, error = _group_name(request.get_json(silent=True))
    if error is None and _name_taken(name, ignore_id=group.id):
        error = "Група с такова име вече има."
    if error:
        return jsonify({"ok": False, "errors": {"name": error}}), 400
    group.name = name
    db.session.commit()
    return jsonify({"ok": True, "groups": _group_dicts()})


@admin_schedule_bp.delete("/admin/schedule-groups/<int:group_id>")
def admin_delete_group(group_id):
    """Маха групата от слотовете и от профилите на треньорите. Слот, който остане без
    отбор и без група, се изтрива (иначе би бил празен ред в графика)."""
    group = db.session.get(TrainingGroup, group_id)
    if group is None:
        return _error("Групата не е намерена.", 404)
    affected = list(group.training_slots)
    db.session.delete(group)  # връзките със слотове и треньори се трият каскадно
    db.session.flush()
    removed = 0
    for slot in affected:
        if not slot.teams and not slot.groups and not slot.label:
            db.session.delete(slot)
            removed += 1
    db.session.commit()
    return jsonify({"ok": True, "slots_removed": removed, "groups": _group_dicts()})
