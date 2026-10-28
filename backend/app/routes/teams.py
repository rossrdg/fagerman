"""Отбори: публичен списък и страница на отбор + админ API.

Публично:  GET /api/teams              активните отбори (началната страница)
           GET /teams/<slug>           страницата на отбора (/teams/2020)
Админ:     /api/admin/teams[/<id>]     създаване, редакция, архивиране
           DELETE /api/admin/teams/<id> истинско изтриване — само главен админ,
                                        и само за вече архивиран отбор
"""
from flask import Blueprint, jsonify, redirect, render_template, request

from app import db
from app.auth import check_admin
from app.models import KIND_MEN, KIND_YOUTH, TEAM_ACTIVE, TEAM_ARCHIVED, Album, Team, Video
from app.routes.news import DEFAULT_SHARE_IMAGE, _absolute
from app.gallery_utils import album_cover, bg_date, photo_urls, remove_files
from app.schedule_utils import build_public_schedule
from app.team_utils import (
    auto_label, cohort_label, cohort_slug, cohort_text, get_season_end_year,
    season_text, sort_key, u_label,
)

teams_bp = Blueprint("teams", __name__)              # /api/teams
admin_teams_bp = Blueprint("admin_teams", __name__)  # /api/admin/teams
page_bp = Blueprint("team_page", __name__)           # /teams/<slug>

admin_teams_bp.before_request(check_admin)  # само влезли потребители (собственик или треньор)

MAX_DESCRIPTION = 160
MAX_LABEL = 12


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


# ---------------------------------------------------------------- helpers ---
def public_dict(team, season_end):
    return {
        "slug": team.slug,
        "url": f"/teams/{team.slug}",
        "kind": team.kind,
        "u_label": u_label(team, season_end),
        "cohort": cohort_text(team),
        "cohort_label": cohort_label(team),
        "description": team.description or "",
    }


def admin_dict(team, season_end):
    data = public_dict(team, season_end)
    data.update({
        "id": team.id,
        "status": team.status,
        "birth_year_from": team.birth_year_from,
        "birth_year_to": team.birth_year_to,
        "u_override": team.u_override or "",
        "u_auto": auto_label(team, season_end),
        "created_at": team.created_at.isoformat() if team.created_at else None,
        "updated_at": team.updated_at.isoformat() if team.updated_at else None,
    })
    return data


def _sorted(teams):
    return sorted(teams, key=sort_key)


def _unique_slug(base):
    slug, n = base, 2
    while Team.query.filter_by(slug=slug).first() is not None:
        slug = f"{base}-{n}"
        n += 1
    return slug


def _year(value):
    """Цяло число от JSON (приема и текст като „2020“). None при празно."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, str):
        value = value.strip()
        if not value.isdigit():
            raise ValueError
    number = int(value)
    return number


def _apply(team, data, creating, season_end):
    """Проверява заявката и я прилага върху отбора. Връща речник с грешки."""
    errors = {}

    if creating:
        kind = data.get("kind", KIND_YOUTH)
        if kind not in (KIND_YOUTH, KIND_MEN):
            errors["kind"] = "Невалиден вид отбор."
        else:
            team.kind = kind

    if team.kind == KIND_MEN:
        team.birth_year_from = None
        team.birth_year_to = None
    elif "birth_year_from" in data or "birth_year_to" in data or creating:
        try:
            year_from = _year(data.get("birth_year_from", team.birth_year_from))
            year_to = _year(data.get("birth_year_to", team.birth_year_to))
        except ValueError:
            errors["birth_year_from"] = "Въведете година, например 2020."
        else:
            low, high = season_end - 20, season_end - 3
            if year_from is None:
                errors["birth_year_from"] = "Въведете годината на набора."
            elif not low <= year_from <= high:
                errors["birth_year_from"] = f"Годината трябва да е между {low} и {high}."
            elif year_to == year_from:
                year_to = None
            if "birth_year_from" not in errors and year_to is not None and year_to != year_from + 1:
                errors["birth_year_to"] = "Втората година трябва да е следващата (напр. 2014 и 2015)."
            if not errors.get("birth_year_from") and not errors.get("birth_year_to"):
                clash = Team.query.filter_by(kind=KIND_YOUTH, birth_year_from=year_from, birth_year_to=year_to)
                if team.id is not None:
                    clash = clash.filter(Team.id != team.id)
                if clash.first() is not None:
                    errors["birth_year_from"] = "Вече има отбор с този набор."
                else:
                    team.birth_year_from, team.birth_year_to = year_from, year_to

    if creating and team.kind == KIND_MEN and not errors:
        if Team.query.filter_by(kind=KIND_MEN).first() is not None:
            errors["kind"] = "Мъжкият отбор вече съществува."

    if "u_override" in data:
        value = data["u_override"]
        if value is not None and not isinstance(value, str):
            errors["u_override"] = "Невалидна стойност."
        else:
            value = (value or "").strip()
            if len(value) > MAX_LABEL:
                errors["u_override"] = f"Максимум {MAX_LABEL} символа."
            else:
                team.u_override = value or None

    if "description" in data:
        value = data["description"]
        if value is not None and not isinstance(value, str):
            errors["description"] = "Невалидна стойност."
        else:
            value = (value or "").strip()
            if len(value) > MAX_DESCRIPTION:
                errors["description"] = f"Максимум {MAX_DESCRIPTION} символа."
            else:
                team.description = value
    elif creating:
        team.description = ""

    if "status" in data:
        if data["status"] not in (TEAM_ACTIVE, TEAM_ARCHIVED):
            errors["status"] = "Невалиден статус."
        else:
            team.status = data["status"]
    elif creating:
        team.status = TEAM_ACTIVE

    return errors


# ----------------------------------------------------------------- public ---
@teams_bp.get("/teams")
def list_teams():
    season_end = get_season_end_year()
    teams = _sorted(Team.query.filter_by(status=TEAM_ACTIVE).all())
    return jsonify({
        "ok": True,
        "season": season_text(season_end),
        "teams": [public_dict(t, season_end) for t in teams],
    })


@page_bp.get("/teams")
@page_bp.get("/teams/")
def teams_index():
    return redirect("/#teams")


def _public_albums(team):
    """Албуми за страницата на отбора: видими и с поне една снимка."""
    albums = (Album.query.filter_by(team_id=team.id, is_hidden=False)
              .order_by(Album.event_date.desc(), Album.id.desc()).all())
    result = []
    for album in albums:
        cover = album_cover(album)
        if cover is None:
            continue
        result.append({
            "title": album.title,
            "date_text": bg_date(album.event_date),
            "count": len(album.photos),
            "cover": photo_urls(cover)[1],
            "url": f"/teams/{team.slug}/albums/{album.id}",
        })
    return result


def _public_videos(team):
    videos = Video.query.filter_by(team_id=team.id).order_by(Video.id.desc()).all()
    return [{"id": v.youtube_id, "title": v.title or "Клип от отбора",
             "watch_url": f"https://www.youtube.com/watch?v={v.youtube_id}"} for v in videos]


@page_bp.get("/teams/<slug>")
def team_page(slug):
    team = Team.query.filter_by(slug=slug, status=TEAM_ACTIVE).first()
    if team is None:
        return render_template("team_page.html", team=None), 404

    season_end = get_season_end_year()
    data = public_dict(team, season_end)
    page_url = _absolute(data["url"])
    if team.kind == KIND_MEN:
        title = "Мъжки отбор"
        about = "Мъжкият отбор на Футболна Академия Герман."
    else:
        title = f"{data['u_label']} — {data['cohort_label']}"
        about = f"{data['u_label']} ({data['cohort_label']}) във Футболна Академия Герман, Герман, район Панчарево, София."
    return render_template(
        "team_page.html",
        team=data,
        title=title,
        description=data["description"] or about,
        page_url=page_url,
        image_url=_absolute(DEFAULT_SHARE_IMAGE),
        season=season_text(season_end),
        schedule=build_public_schedule(highlight_slug=team.slug),
        albums=_public_albums(team),
        videos=_public_videos(team),
    )


# ------------------------------------------------------------------ admin ---
@admin_teams_bp.get("/admin/teams")
def admin_list():
    season_end = get_season_end_year()
    teams = _sorted(Team.query.all())
    return jsonify({
        "ok": True,
        "season": season_text(season_end),
        "season_end_year": season_end,
        "teams": [admin_dict(t, season_end) for t in teams],
    })


@admin_teams_bp.get("/admin/teams/<int:team_id>")
def admin_get(team_id):
    team = db.session.get(Team, team_id)
    if team is None:
        return _error("Отборът не е намерен.", 404)
    return jsonify({"ok": True, "team": admin_dict(team, get_season_end_year())})


@admin_teams_bp.post("/admin/teams")
def admin_create():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")

    season_end = get_season_end_year()
    team = Team()
    errors = _apply(team, data, creating=True, season_end=season_end)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    base = "men" if team.kind == KIND_MEN else cohort_slug(team.birth_year_from, team.birth_year_to)
    team.slug = _unique_slug(base)
    db.session.add(team)
    db.session.commit()
    return jsonify({"ok": True, "team": admin_dict(team, season_end)}), 201


@admin_teams_bp.patch("/admin/teams/<int:team_id>")
def admin_update(team_id):
    team = db.session.get(Team, team_id)
    if team is None:
        return _error("Отборът не е намерен.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")

    season_end = get_season_end_year()
    errors = _apply(team, data, creating=False, season_end=season_end)
    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400

    db.session.commit()
    return jsonify({"ok": True, "team": admin_dict(team, season_end)})


@admin_teams_bp.delete("/admin/teams/<int:team_id>")
def admin_delete(team_id):
    # „Изтрий“ в списъка само архивира (PATCH status). Истинското изтриване е
    # само за главния администратор и само за отбор, който вече е архивиран.
    denied = check_admin(owner_only=True)
    if denied is not None:
        return denied
    team = db.session.get(Team, team_id)
    if team is None:
        return _error("Отборът не е намерен.", 404)
    if team.status != TEAM_ARCHIVED:
        return _error("Първо архивирайте отбора.", 409)
    names = [photo.name for album in team.albums for photo in album.photos]
    db.session.delete(team)  # албумите, снимките и клиповете се трият заедно с отбора
    db.session.commit()
    remove_files(names)
    return jsonify({"ok": True})
