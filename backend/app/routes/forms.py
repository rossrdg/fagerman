"""Попълване на бланките на БФС от форма (родител) + име на клуба (админ).

  GET  /api/parent/children/<id>/forms/spec      полетата за категорията, предварително попълнени данни
  POST /api/parent/children/<id>/forms/generate  връща готов PDF (заявление + декларация + медицинско)
  GET/PUT /api/admin/settings/club-name          официалното име на клуба за бланките

ЛИЧНИ ДАННИ: заявката за генериране носи ЕГН, лични карти и др. Те се ползват само в паметта за тази
заявка и не се записват никъде (виж app/pdf_forms.py). Тук умишлено няма логване на тялото на заявката,
а грешките са общи съобщения без въведени стойности."""
from datetime import date

from flask import Blueprint, Response, current_app, jsonify, request

from app import db
from app.auth import check_admin
from app.documents_catalog import CATEGORY_LABELS, category_for, ensure_set
from app.models import Player, Setting
from app.parent_auth import current_parent, parent_required
from app.pdf_forms import (
    CLUB_KEY, DEFAULT_CLUB_NAME, FormError, build_pdf, form_groups, get_club_name, validate,
)
from app.routes.players import _manager_only
from app.team_utils import get_season_end_year

parent_forms_bp = Blueprint("parent_forms", __name__)
admin_forms_bp = Blueprint("admin_forms", __name__)
admin_forms_bp.before_request(check_admin)

MAX_BODY = 20_000
MAX_CLUB_NAME = 120


def _error(message, status=400, errors=None):
    body = {"ok": False, "error": message}
    if errors:
        body["errors"] = errors
    return jsonify(body), status


def _player(player_id):
    parent = current_parent()
    player = db.session.get(Player, player_id)
    if player is None or player.parent_id != parent.id or player.archived:
        return None
    return player


@parent_forms_bp.get("/parent/children/<int:player_id>/forms/spec")
@parent_required
def spec(player_id):
    player = _player(player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    season_end = get_season_end_year()
    category = category_for(player, season_end)
    prefill = {
        "p1_name": current_parent().display_name,
        "child_bg": player.child_name,
        "player_bg": player.child_name,
        "date": date.today().isoformat(),
    }
    return jsonify({
        "ok": True,
        "child_name": player.child_name,
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "season": f"{season_end - 1}/{season_end}",
        "club_name": get_club_name(),
        "groups": form_groups(category),
        "prefill": prefill,
    })


@parent_forms_bp.post("/parent/children/<int:player_id>/forms/generate")
@parent_required
def generate(player_id):
    player = _player(player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    if request.content_length is not None and request.content_length > MAX_BODY:
        return _error("Заявката е твърде голяма.", 413)
    season_end = get_season_end_year()
    card, _docs = ensure_set(player, season_end)
    db.session.commit()
    if card.card_received_at:
        return _error("Картотеката вече е получена — не са нужни нови бланки.", 409)

    category = category_for(player, season_end)
    payload = request.get_json(silent=True)
    values = payload.get("values") if isinstance(payload, dict) else None
    try:
        clean = validate(category, values)
        pdf = build_pdf(category, clean, season_end, get_club_name(), player.child_name)
    except FormError as err:
        return _error("Проверете маркираните полета.", 400, err.errors)
    except Exception:  # noqa: BLE001 — умишлено без exc_info/стойности: в данните има ЕГН
        current_app.logger.error("PDF за картотекиране не можа да се генерира.")
        return _error("Документът не можа да се генерира. Опитайте отново.", 500)

    response = Response(pdf, mimetype="application/pdf")
    response.headers["Content-Disposition"] = 'attachment; filename="kartotekirane.pdf"'
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# ------------------------------------------------------------------ админ ---
@admin_forms_bp.get("/admin/settings/club-name")
def get_club():
    denied = _manager_only()
    if denied:
        return denied
    return jsonify({"ok": True, "club_name": get_club_name(), "default": DEFAULT_CLUB_NAME})


@admin_forms_bp.put("/admin/settings/club-name")
def put_club():
    denied = _manager_only()
    if denied:
        return denied
    name = (request.get_json(silent=True) or {}).get("club_name")
    name = " ".join(name.split()) if isinstance(name, str) else ""
    if not name:
        row = db.session.get(Setting, CLUB_KEY)
        if row is not None:
            db.session.delete(row)
            db.session.commit()
        return jsonify({"ok": True, "club_name": DEFAULT_CLUB_NAME, "default": DEFAULT_CLUB_NAME})
    if len(name) > MAX_CLUB_NAME:
        return _error(f"Най-много {MAX_CLUB_NAME} символа.", 400, {"club_name": f"Най-много {MAX_CLUB_NAME} символа."})
    row = db.session.get(Setting, CLUB_KEY)
    if row is None:
        db.session.add(Setting(key=CLUB_KEY, value=name))
    else:
        row.value = name
    db.session.commit()
    return jsonify({"ok": True, "club_name": name, "default": DEFAULT_CLUB_NAME})
