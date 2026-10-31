"""Смяна на сезона (само главен администратор).

  GET  /api/admin/season          преглед на следващата смяна + история на смените
  POST /api/admin/season          потвърждава смяната (body: to_season_end_year, create_new_cohort)
  POST /api/admin/season/restore  връща към ПРЕДИШЕН сезон от историята (body: to_season_end_year)

Правила: U етикетът расте с 1 всяка година, докато стигне U18. Набор, чийто етикет би
станал над U18, преминава в MEN — отборът му се архивира. Ръчно зададените етикети
НИКОГА не се пипат автоматично (показват се в прегледа). Графикът е по набор и не се променя.

Всяка смяна се записва (SeasonSwitch). Връщането към по-стар сезон отменя смените една по
една, от последната назад: възстановява автоматично архивираните отбори и премахва (или
скрива, ако вече имат данни) автоматично създадените нови набори. Другите ръчни промени
(описания, албуми и т.н.) не се връщат."""
import json

from flask import Blueprint, jsonify, request

from app import db
from app.auth import check_admin, current_user
from app.models import KIND_MEN, KIND_YOUTH, TEAM_ACTIVE, TEAM_ARCHIVED, SeasonSwitch, Team
from app.routes.teams import _unique_slug
from app.team_utils import (
    YOUTH_MAX_U, YOUTH_MIN_U, cohort_label, cohort_slug, cohort_text, get_last_switch,
    get_season_end_year, season_text, set_last_switch, set_season_end_year, sort_key, u_label,
)

admin_season_bp = Blueprint("admin_season", __name__)
admin_season_bp.before_request(lambda: check_admin(owner_only=True))


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _new_cohort_year(next_end):
    """Годината на най-малкия набор (U6) за новия сезон — или None, ако вече има такъв отбор."""
    year = next_end - YOUTH_MIN_U
    for team in Team.query.filter_by(kind=KIND_YOUTH).all():
        if team.birth_year_from is not None and team.birth_year_from <= year <= (team.birth_year_to or team.birth_year_from):
            return None
    return year


def _plan(current_end):
    """Какво ще се случи с всеки активен отбор при смяна към current_end + 1."""
    next_end = current_end + 1
    rows = []
    for team in sorted(Team.query.filter_by(status=TEAM_ACTIVE).all(), key=sort_key):
        row = {
            "id": team.id, "kind": team.kind, "cohort": cohort_text(team),
            "cohort_label": cohort_label(team), "old_label": u_label(team, current_end),
            "new_label": None, "action": "men",
        }
        if team.kind == KIND_MEN:
            row["action"] = "men"
        elif team.u_override:
            row["action"] = "manual"  # ръчен етикет — не се пипа и не се архивира автоматично
        else:
            number = next_end - team.birth_year_from
            if number > YOUTH_MAX_U:
                row["action"], row["new_label"] = "archive", "MEN"
            else:
                row["action"], row["new_label"] = "change", f"U{number}"
        rows.append(row)
    return rows


# ----------------------------------------------------------------- история ---
def _import_legacy_switch():
    """Първата версия пазеше само последната смяна в настройките. Ако има такава и
    таблицата е празна, я превръщаме в запис, за да не се загуби."""
    if SeasonSwitch.query.count():
        return
    legacy = get_last_switch()
    if not legacy or "from" not in legacy or "to" not in legacy:
        return
    db.session.add(SeasonSwitch(
        from_end=legacy["from"], to_end=legacy["to"],
        archived_ids=json.dumps(legacy.get("archived", [])), created_team_id=legacy.get("created"),
        switched_by="(стара версия)",
    ))
    set_last_switch(None)
    db.session.commit()


def _archived_ids(record):
    try:
        ids = json.loads(record.archived_ids or "[]")
    except ValueError:
        return []
    return [i for i in ids if isinstance(i, int)]


def _history():
    """Смените, най-новата първо, с четими данни за таблицата/потвърждението."""
    _import_legacy_switch()
    result = []
    for record in SeasonSwitch.query.order_by(SeasonSwitch.id.desc()).all():
        archived = [t for t in (db.session.get(Team, i) for i in _archived_ids(record)) if t is not None]
        created = db.session.get(Team, record.created_team_id) if record.created_team_id else None
        result.append({
            "id": record.id,
            "from_end": record.from_end, "from_text": season_text(record.from_end),
            "to_end": record.to_end, "to_text": season_text(record.to_end),
            "archived": [cohort_label(t) for t in archived],
            "created": cohort_text(created) if created is not None else None,
            "by": record.switched_by,
            "at": record.created_at.isoformat() if record.created_at else None,
        })
    return result


def _undo_record(record):
    for team_id in _archived_ids(record):
        team = db.session.get(Team, team_id)
        if team is not None and team.status == TEAM_ARCHIVED:
            team.status = TEAM_ACTIVE

    created = db.session.get(Team, record.created_team_id) if record.created_team_id else None
    if created is not None:
        if created.albums or created.videos or created.training_slots:
            created.status = TEAM_ARCHIVED  # вече има данни — не го трием, само го скриваме
        else:
            db.session.delete(created)
    db.session.delete(record)


@admin_season_bp.get("/admin/season")
def preview():
    current = get_season_end_year()
    history = _history()
    new_year = _new_cohort_year(current + 1)
    return jsonify({
        "ok": True,
        "current_end": current, "current_text": season_text(current),
        "next_end": current + 1, "next_text": season_text(current + 1),
        "max_u": YOUTH_MAX_U,
        "rows": _plan(current),
        "new_cohort": None if new_year is None else {"year": new_year, "label": f"U{current + 1 - new_year}"},
        "history": history,
    })


@admin_season_bp.post("/admin/season")
def confirm():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    current = get_season_end_year()
    # Защита от двойно натискане / стар прозорец: потвърждава се точно „следващия" сезон.
    if data.get("to_season_end_year") != current + 1:
        return _error("Сезонът вече е сменен или данните са остарели. Презаредете страницата.", 409)

    next_end = current + 1
    archived = []
    for row in _plan(current):
        if row["action"] == "archive":
            team = db.session.get(Team, row["id"])
            team.status = TEAM_ARCHIVED
            archived.append(team.id)

    created_id = None
    if data.get("create_new_cohort") is True:
        year = _new_cohort_year(next_end)
        if year is not None:
            team = Team(kind=KIND_YOUTH, birth_year_from=year, birth_year_to=None, status=TEAM_ACTIVE,
                        description="", slug=_unique_slug(cohort_slug(year, None)))
            db.session.add(team)
            db.session.flush()
            created_id = team.id

    user = current_user()
    set_season_end_year(next_end)
    db.session.add(SeasonSwitch(
        from_end=current, to_end=next_end, archived_ids=json.dumps(archived),
        created_team_id=created_id, switched_by=(user.username if user else "")[:80],
    ))
    db.session.commit()
    return jsonify({"ok": True, "season": season_text(next_end), "archived": len(archived), "created": created_id is not None})


@admin_season_bp.post("/admin/season/restore")
def restore():
    """Връща към избран по-стар сезон, като отменя смените от последната назад."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("to_season_end_year"), int):
        return _error("Невалидна заявка.")
    target = data["to_season_end_year"]
    current = get_season_end_year()
    if target >= current:
        return _error("Изберете по-стар сезон от текущия.", 409)

    _import_legacy_switch()
    to_undo, expected = [], current
    for record in SeasonSwitch.query.order_by(SeasonSwitch.id.desc()).all():
        if expected == target:
            break
        if record.to_end != expected:
            return _error("Историята на сезоните е прекъсната и не може да се върне автоматично.", 409)
        to_undo.append(record)
        expected = record.from_end
    if expected != target:
        return _error("Този сезон не е в историята.", 409)

    for record in to_undo:
        _undo_record(record)
    set_season_end_year(target)
    db.session.commit()
    return jsonify({"ok": True, "season": season_text(target), "undone": len(to_undo)})
