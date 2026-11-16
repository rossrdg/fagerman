"""Такси (админ) + напомняния за родителя.

Админ (само главен админ и главен треньор; обикновен треньор не вижда такси):
  GET/POST  /api/admin/fee-types, PATCH /api/admin/fee-types/<id>       видове такси
  POST      /api/admin/fees/assign                                       присвоява такса на отбор / играчи
  PATCH/DELETE /api/admin/fee-assignments/<id>                           промяна / край на присвояване
  GET       /api/admin/fees/month?month=ГГГГ-ММ&team=&type=&q=           екранът „месец + отбор“
  PATCH     /api/admin/fee-charges/<id>                                  статус, сума, бележка на един ред
  POST      /api/admin/fees/bulk                                         „всички платени“ / „освободи месеци“
  GET       /api/admin/players/<id>/fees                                 такси на детето („платено до …“, история)
  GET       /api/admin/fees/report[.csv]                                 неплатили по месец/отбор
  GET/PUT   /api/admin/fees/pay-info                                     текст „Как се плаща“
Родител:
  GET       /api/parent/messages                                         напомняния (такси, документи за поправка)

Всяка промяна на плащане/сума/присвояване се записва в историята (кой и кога)."""
import csv
import io

from flask import Blueprint, Response, jsonify, request

from app import db
from app.announcement_utils import date_text, visible_for_parent
from app.auth import check_admin, current_user
from app.fee_utils import (
    MAX_MONTHS_AHEAD, PAY_INFO_KEY, STATUS_LABELS, add_months, charge_label, current_month, due_charges, ensure_all,
    ensure_charges, ensure_player, euros, get_pay_info, log, money, month_key, month_label, parse_amount,
    parse_month, player_summary,
)
from app.models import (
    DOC_RETURNED, FEE_MONTHLY, FEE_ONE_TIME, FEE_PAID, FEE_STATUSES, FEE_UNPAID, FEE_WAIVED, FeeAssignment,
    FeeCharge, FeeHistory, FeeType, PlayerDocument, Player, PortalText, Team, utcnow,
)
from app.parent_auth import current_parent, parent_required
from app.player_utils import player_team
from app.routes.players import _manager_only, _who
from app.team_utils import get_season_end_year, sort_key, u_label

admin_fees_bp = Blueprint("admin_fees", __name__)
admin_fees_bp.before_request(check_admin)
parent_messages_bp = Blueprint("parent_messages", __name__)

MAX_NAME = 80
MAX_NOTE = 120
MAX_PAY_INFO = 1500


def _error(message, status=400, errors=None):
    body = {"ok": False, "error": message}
    if errors:
        body["errors"] = errors
    return jsonify(body), status


def _int(value):
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value, limit):
    text = " ".join(value.split()) if isinstance(value, str) else ""
    return text[:limit] if len(text) <= limit else None


@admin_fees_bp.before_request
def _managers_only():
    return _manager_only() if current_user() is not None else None


# ---------------------------------------------------------------- речници ---
def type_dict(t):
    return {"id": t.id, "name": t.name, "kind": t.kind, "is_active": bool(t.is_active),
            "default_amount": euros(t.default_amount_cents), "default_amount_text": money(t.default_amount_cents),
            "assignments": len(FeeAssignment.query.filter_by(fee_type_id=t.id).all())}


def charge_dict(c, season_end=None):
    player = db.session.get(Player, c.player_id)
    team = player_team(player)[0]
    return {
        "id": c.id, "assignment_id": c.assignment_id, "player_id": c.player_id,
        "child_name": player.child_name,
        "team_label": u_label(team, season_end or get_season_end_year()) if team else "",
        "fee_type_id": c.fee_type_id, "type_name": c.fee_type.name, "kind": c.fee_type.kind,
        "month": month_key(c.month), "month_label": month_label(c.month),
        "label": charge_label(c),
        "amount": euros(c.amount_cents), "amount_cents": c.amount_cents, "amount_text": money(c.amount_cents),
        "status": c.status, "status_label": STATUS_LABELS[c.status], "note": c.note,
        "paid_at": c.paid_at.isoformat() if c.paid_at else None,
        "updated_by": c.updated_by, "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def assignment_dict(a):
    return {
        "id": a.id, "fee_type_id": a.fee_type_id, "type_name": a.fee_type.name, "kind": a.fee_type.kind,
        "start_month": month_key(a.start_month), "start_label": month_label(a.start_month),
        "end_month": month_key(a.end_month) if a.end_month else None,
        "amount": euros(a.amount_cents), "amount_text": money(a.amount_cents),
        "first_month_amount": euros(a.first_month_amount_cents) if a.first_month_amount_cents is not None else None,
        "note": a.note,
    }


# -------------------------------------------------------------- видове ---
@admin_fees_bp.get("/admin/fee-types")
def list_types():
    types = FeeType.query.order_by(FeeType.is_active.desc(), FeeType.name).all()
    return jsonify({"ok": True, "types": [type_dict(t) for t in types]})


def _apply_type(t, data, creating):
    errors = {}
    if "name" in data or creating:
        name = _text(data.get("name"), MAX_NAME)
        if not name:
            errors["name"] = "Въведете име на таксата (до 80 символа)."
        else:
            clash = [x for x in FeeType.query.all() if x.name.casefold() == name.casefold() and x.id != t.id]
            if clash:
                errors["name"] = "Такса с такова име вече има."
            else:
                t.name = name
    if creating or "kind" in data:
        kind = data.get("kind", FEE_MONTHLY)
        if kind not in (FEE_MONTHLY, FEE_ONE_TIME):
            errors["kind"] = "Изберете месечна или еднократна."
        elif not creating and kind != t.kind and FeeAssignment.query.filter_by(fee_type_id=t.id).first():
            errors["kind"] = "Видът не се сменя, след като таксата е присвоена."
        else:
            t.kind = kind
    if creating or "default_amount" in data:
        try:
            t.default_amount_cents = parse_amount(data.get("default_amount", 0))
        except ValueError:
            errors["default_amount"] = "Въведете сума в евро, напр. 30 или 30,50."
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            errors["is_active"] = "Невалидна стойност."
        else:
            t.is_active = data["is_active"]
    return errors


@admin_fees_bp.post("/admin/fee-types")
def create_type():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    t = FeeType()
    errors = _apply_type(t, data, creating=True)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    db.session.add(t)
    db.session.commit()
    return jsonify({"ok": True, "type": type_dict(t)}), 201


@admin_fees_bp.patch("/admin/fee-types/<int:type_id>")
def update_type(type_id):
    t = db.session.get(FeeType, type_id)
    if t is None:
        return _error("Таксата не е намерена.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    errors = _apply_type(t, data, creating=False)
    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400
    db.session.commit()
    return jsonify({"ok": True, "type": type_dict(t)})


# ------------------------------------------------------------ присвояване ---
def _target_players(data):
    """Играчите за масово присвояване: отбор, списък или всички активни."""
    if data.get("all") is True:
        players = Player.query.filter_by(archived=False, status="active").all()
    elif _int(data.get("team_id")) is not None:
        team_id = _int(data.get("team_id"))
        players = [p for p in Player.query.filter_by(archived=False, status="active").all()
                   if (player_team(p)[0] and player_team(p)[0].id == team_id)]
    elif isinstance(data.get("player_ids"), list):
        ids = [i for i in (_int(x) for x in data["player_ids"]) if i is not None]
        players = Player.query.filter(Player.id.in_(ids), Player.archived.is_(False)).all() if ids else []
    else:
        return None
    return players


@admin_fees_bp.post("/admin/fees/assign")
def assign():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    errors = {}
    fee_type = db.session.get(FeeType, _int(data.get("fee_type_id")) or 0)
    if fee_type is None or not fee_type.is_active:
        errors["fee_type_id"] = "Изберете активна такса."
    try:
        start = parse_month(data.get("start_month"))
    except (ValueError, AttributeError):
        errors["start_month"] = "Изберете начален месец."
        start = None
    amount = fee_type.default_amount_cents if fee_type is not None else 0
    if data.get("amount") not in (None, ""):
        try:
            amount = parse_amount(data["amount"])
        except ValueError:
            errors["amount"] = "Въведете сума в евро, напр. 30 или 30,50."
    first = None
    if data.get("first_month_amount") not in (None, ""):
        try:
            first = parse_amount(data["first_month_amount"])
        except ValueError:
            errors["first_month_amount"] = "Въведете сума в евро."
    note = _text(data.get("note") or "", MAX_NOTE)
    if note is None:
        errors["note"] = f"Бележката е до {MAX_NOTE} символа."
    players = _target_players(data)
    if players is None:
        errors["target"] = "Изберете отбор, играчи или „всички“."
    elif not players and "target" not in errors:
        errors["target"] = "Няма подходящи играчи."
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    created, skipped = 0, []
    for player in players:
        clash = [a for a in player.fee_assignments if a.fee_type_id == fee_type.id
                 and (a.end_month is None or a.end_month >= start)]
        if clash:
            skipped.append(player.child_name)
            continue
        assignment = FeeAssignment(player=player, fee_type=fee_type, start_month=start, amount_cents=amount,
                                   first_month_amount_cents=first, note=note or "", created_by=_who())
        db.session.add(assignment)
        db.session.flush()
        ensure_charges(assignment)
        log(player.id, "assign", f"{fee_type.name}: {money(amount)} от {month_label(start)}"
            + (f" (първи месец {money(first)})" if first is not None else ""), _who(), assignment=assignment)
        created += 1
    db.session.commit()
    return jsonify({"ok": True, "created": created, "skipped": skipped}), 201


@admin_fees_bp.patch("/admin/fee-assignments/<int:assignment_id>")
def update_assignment(assignment_id):
    a = db.session.get(FeeAssignment, assignment_id)
    if a is None:
        return _error("Присвояването не е намерено.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    errors, notes = {}, []
    ensure_charges(a)  # редовете до сега се създават със старата сума
    if "amount" in data:
        try:
            cents = parse_amount(data["amount"])
        except ValueError:
            errors["amount"] = "Въведете сума в евро."
        else:
            if cents != a.amount_cents:
                notes.append(f"сума {money(a.amount_cents)} → {money(cents)} (за следващите месеци)")
                a.amount_cents = cents
                if data.get("apply_to_unpaid") is True:
                    changed = 0
                    for c in a.charges:
                        if c.status == FEE_UNPAID and c.amount_cents != cents:
                            c.amount_cents, c.updated_by = cents, _who()
                            changed += 1
                    notes.append(f"приложена и към {changed} неплатени реда")
    if "end_month" in data:
        if data["end_month"] in (None, ""):
            a.end_month = None
            notes.append("краят е премахнат")
        else:
            try:
                a.end_month = parse_month(data["end_month"])
                notes.append(f"край: {month_label(a.end_month)}")
            except (ValueError, AttributeError):
                errors["end_month"] = "Невалиден месец."
    if "note" in data:
        note = _text(data["note"] or "", MAX_NOTE)
        if note is None:
            errors["note"] = f"Бележката е до {MAX_NOTE} символа."
        else:
            a.note = note
    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400
    if notes:
        log(a.player_id, "assignment", f"{a.fee_type.name}: " + "; ".join(notes), _who(), assignment=a)
    db.session.commit()
    return jsonify({"ok": True, "assignment": assignment_dict(a)})


@admin_fees_bp.delete("/admin/fee-assignments/<int:assignment_id>")
def delete_assignment(assignment_id):
    a = db.session.get(FeeAssignment, assignment_id)
    if a is None:
        return _error("Присвояването не е намерено.", 404)
    if any(c.status != FEE_UNPAID for c in a.charges):
        return _error("Има платени или освободени месеци. Задайте край на присвояването вместо да го изтривате.", 409)
    log(a.player_id, "assign_removed", f"{a.fee_type.name} от {month_label(a.start_month)} е премахнато", _who())
    db.session.delete(a)
    db.session.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------ месец + отбор ---
def _filtered_charges(month_filter, args):
    """Редове за месеци (списък) по филтри: team, type, q. Само за неархивирани играчи."""
    query = FeeCharge.query.join(Player, FeeCharge.player_id == Player.id).filter(Player.archived.is_(False))
    if month_filter is not None:
        query = query.filter(FeeCharge.month.in_(month_filter))
    type_id = _int(args.get("type"))
    if type_id:
        query = query.filter(FeeCharge.fee_type_id == type_id)
    charges = query.all()
    team_id = _int(args.get("team"))
    if team_id:
        charges = [c for c in charges if (player_team(db.session.get(Player, c.player_id))[0] or Team()).id == team_id]
    needle = (args.get("q") or "").strip().casefold()
    if needle:
        charges = [c for c in charges if needle in db.session.get(Player, c.player_id).child_name.casefold()]
    return charges


def _totals(charges):
    t = {"count": len(charges), "unpaid": 0, "paid": 0, "waived": 0, "due": 0}
    for c in charges:
        t[c.status] += c.amount_cents
        if c.status != FEE_WAIVED:
            t["due"] += c.amount_cents
    return {"count": t["count"], "unpaid_text": money(t["unpaid"]), "paid_text": money(t["paid"]),
            "waived_text": money(t["waived"]), "due_text": money(t["due"]),
            "unpaid_cents": t["unpaid"], "paid_cents": t["paid"], "due_cents": t["due"]}


def _options():
    season_end = get_season_end_year()
    teams = sorted(Team.query.filter_by(status="active").all(), key=sort_key)
    types = FeeType.query.order_by(FeeType.is_active.desc(), FeeType.name).all()
    return {"teams": [{"id": t.id, "label": u_label(t, season_end)} for t in teams],
            "types": [type_dict(t) for t in types]}


@admin_fees_bp.get("/admin/fees/month")
def month_view():
    try:
        month = parse_month(request.args.get("month") or month_key(current_month()))
    except (ValueError, AttributeError):
        return _error("Невалиден месец.")
    ensure_all()
    db.session.commit()
    charges = _filtered_charges([month], request.args)
    season_end = get_season_end_year()
    rows = sorted((charge_dict(c, season_end) for c in charges),
                  key=lambda r: (r["team_label"], r["child_name"].casefold(), r["type_name"]))
    return jsonify({"ok": True, "month": month_key(month), "month_label": month_label(month),
                    "prev": month_key(add_months(month, -1)), "next": month_key(add_months(month, 1)),
                    "is_current": month == current_month(), "rows": rows, "totals": _totals(charges),
                    **_options()})


@admin_fees_bp.patch("/admin/fee-charges/<int:charge_id>")
def update_charge(charge_id):
    c = db.session.get(FeeCharge, charge_id)
    if c is None:
        return _error("Редът не е намерен.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    errors, notes = {}, []
    if "status" in data:
        if data["status"] not in FEE_STATUSES:
            errors["status"] = "Невалиден статус."
        elif data["status"] != c.status:
            notes.append(f"статус {STATUS_LABELS[c.status]} → {STATUS_LABELS[data['status']]}")
            c.status = data["status"]
            c.paid_at = utcnow() if c.status == FEE_PAID else None
    if "amount" in data:
        try:
            cents = parse_amount(data["amount"])
        except ValueError:
            errors["amount"] = "Въведете сума в евро."
        else:
            if cents != c.amount_cents:
                notes.append(f"сума {money(c.amount_cents)} → {money(cents)}")
                c.amount_cents = cents
    if "note" in data:
        note = _text(data["note"] or "", MAX_NOTE)
        if note is None:
            errors["note"] = f"Бележката е до {MAX_NOTE} символа."
        elif note != c.note:
            notes.append("бележка" + (f": {note}" if note else " е изтрита"))
            c.note = note
    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400
    if notes:
        c.updated_by = _who()
        log(c.player_id, "charge", f"{charge_label(c)}: " + "; ".join(notes), _who(), charge=c)
    db.session.commit()
    return jsonify({"ok": True, "charge": charge_dict(c)})


@admin_fees_bp.post("/admin/fees/bulk")
def bulk():
    """Масово: неплатените редове за избрани месеци (и отбор/такса/играчи) стават платени или освободени."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    status = data.get("status")
    if status not in (FEE_PAID, FEE_WAIVED):
        return _error("Изберете „платено“ или „освободено“.")
    raw_months = data.get("months")
    try:
        months = sorted({parse_month(m) for m in raw_months}) if isinstance(raw_months, list) and raw_months else []
    except (ValueError, AttributeError):
        months = []
    if not months or len(months) > 24:
        return _error("Изберете от 1 до 24 месеца.", 400, {"months": "Изберете от 1 до 24 месеца."})
    horizon = add_months(current_month(), MAX_MONTHS_AHEAD)
    if months[-1] > horizon:
        return _error(f"Може да се избират месеци най-много {MAX_MONTHS_AHEAD} напред.", 400, {"months": "Твърде далечен месец."})
    # Освобождаването за месеци напред (напр. лятото) предварително създава редовете им — само за избраните играчи.
    if status == FEE_WAIVED:
        has_team = _int(data.get("team_id")) is not None
        has_ids = isinstance(data.get("player_ids"), list)
        targets = _target_players({"team_id": data.get("team_id"), "player_ids": data.get("player_ids"),
                                   "all": not (has_team or has_ids)}) or []
        type_id = _int(data.get("type_id"))
        for player in targets:
            for assignment in player.fee_assignments:
                if type_id is None or assignment.fee_type_id == type_id:
                    ensure_charges(assignment, max(months[-1], current_month()))
    else:
        ensure_all()
    args = {"team": data.get("team_id"), "type": data.get("type_id")}
    charges = [c for c in _filtered_charges(months, args) if c.status == FEE_UNPAID]
    if isinstance(data.get("player_ids"), list):
        ids = {i for i in (_int(x) for x in data["player_ids"]) if i is not None}
        charges = [c for c in charges if c.player_id in ids]
    when = utcnow()
    for c in charges:
        c.status = status
        c.paid_at = when if status == FEE_PAID else None
        c.updated_by = _who()
        log(c.player_id, "charge", f"{charge_label(c)}: статус Неплатено → {STATUS_LABELS[status]} (масово)", _who(), charge=c)
    db.session.commit()
    return jsonify({"ok": True, "changed": len(charges)})


# -------------------------------------------------------- такси на детето ---
@admin_fees_bp.get("/admin/players/<int:player_id>/fees")
def player_fees(player_id):
    player = db.session.get(Player, player_id)
    if player is None:
        return _error("Профилът не е намерен.", 404)
    ensure_player(player)
    db.session.commit()
    season_end = get_season_end_year()
    charges = sorted(FeeCharge.query.filter_by(player_id=player.id).all(), key=lambda c: (c.month, c.id), reverse=True)
    history = FeeHistory.query.filter_by(player_id=player.id).order_by(FeeHistory.id.desc()).limit(60).all()
    options = _options()
    return jsonify({
        "ok": True,
        "player": {"id": player.id, "child_name": player.child_name, "archived": bool(player.archived), "status": player.status},
        "summary": player_summary(player),
        "assignments": [assignment_dict(a) for a in player.fee_assignments],
        "charges": [charge_dict(c, season_end) for c in charges],
        "history": [{"action": h.action, "detail": h.detail, "by": h.by, "at": h.at.isoformat() if h.at else None} for h in history],
        "types": options["types"],
    })


# ------------------------------------------------------------------ отчет ---
def _report_rows(args):
    try:
        month = parse_month(args.get("month") or month_key(current_month()))
    except (ValueError, AttributeError):
        return None, None
    ensure_all()
    db.session.commit()
    charges = _filtered_charges([month], args)
    if args.get("status", "unpaid") != "all":
        charges = [c for c in charges if c.status == FEE_UNPAID]
    return month, charges


@admin_fees_bp.get("/admin/fees/report")
def report():
    month, charges = _report_rows(request.args)
    if month is None:
        return _error("Невалиден месец.")
    season_end = get_season_end_year()
    rows = sorted((charge_dict(c, season_end) for c in charges),
                  key=lambda r: (r["team_label"], r["child_name"].casefold()))
    return jsonify({"ok": True, "month": month_key(month), "month_label": month_label(month),
                    "rows": rows, "totals": _totals(charges)})


@admin_fees_bp.get("/admin/fees/report.csv")
def report_csv():
    month, charges = _report_rows(request.args)
    if month is None:
        return _error("Невалиден месец.")
    season_end = get_season_end_year()
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(["Месец", "Дете", "Отбор", "Родител", "Телефон", "Такса", "Сума (€)", "Статус"])
    for c in sorted(charges, key=lambda c: (c.player_id, c.id)):
        d = charge_dict(c, season_end)
        parent = db.session.get(Player, c.player_id).parent
        writer.writerow([d["month_label"], d["child_name"], d["team_label"], parent.display_name, parent.phone,
                         d["type_name"], f"{c.amount_cents / 100:.2f}".replace(".", ","), d["status_label"]])
    response = Response("\ufeff" + out.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="taxi-{month_key(month)}.csv"'
    response.headers["Cache-Control"] = "private, no-store"
    return response


# ------------------------------------------------------------ „Как се плаща“ ---
@admin_fees_bp.get("/admin/fees/pay-info")
def get_pay():
    return jsonify({"ok": True, "text": get_pay_info()})


@admin_fees_bp.put("/admin/fees/pay-info")
def put_pay():
    text = (request.get_json(silent=True) or {}).get("text")
    text = text.strip() if isinstance(text, str) else ""
    if len(text) > MAX_PAY_INFO:
        return _error(f"Най-много {MAX_PAY_INFO} символа.", 400, {"text": f"Най-много {MAX_PAY_INFO} символа."})
    row = db.session.get(PortalText, PAY_INFO_KEY)
    if row is None:
        db.session.add(PortalText(key=PAY_INFO_KEY, value=text))
    else:
        row.value = text
    db.session.commit()
    return jsonify({"ok": True, "text": text})


# ----------------------------------------------------------------- родител ---
def build_reminders(parent):
    """Автоматични напомняния за родителя: дължими такси и документи за поправка. Спокоен тон, без срокове."""
    reminders = []
    season_end = get_season_end_year()
    players = Player.query.filter_by(parent_id=parent.id, archived=False).order_by(Player.child_name).all()
    for player in players:
        ensure_player(player)
        due = due_charges(FeeCharge.query.filter_by(player_id=player.id).all())
        if due:
            total = sum(c.amount_cents for c in due)
            reminders.append({
                "type": "fees", "child_id": player.id, "child_name": player.child_name,
                "items": [{"label": charge_label(c), "amount_text": money(c.amount_cents)} for c in due],
                "total_text": money(total),
                "text": f"За {player.child_name} има неплатени такси. Ако вече сте платили, ще го отбележим скоро.",
            })
        returned = PlayerDocument.query.filter_by(player_id=player.id, season_end=season_end, status=DOC_RETURNED,
                                                  archived=False).count()
        if returned:
            reminders.append({
                "type": "documents", "child_id": player.id, "child_name": player.child_name, "count": returned,
                "text": f"За {player.child_name} има документ, който треньорът е помолил да се поправи — вижте коментара.",
            })
    db.session.commit()
    return reminders


@parent_messages_bp.get("/parent/messages")
@parent_required
def parent_messages():
    parent = current_parent()
    reminders = build_reminders(parent)
    announcements = [{
        "id": a.id, "title": a.title, "body": a.body, "date_text": date_text(a.publish_date),
        # За известие към отбор/дете се показва за кое дете е (ако родителят има няколко).
        "for_children": [c.child_name for c in who] if a.audience != "all" else [],
    } for a, who in visible_for_parent(parent)]
    return jsonify({
        "ok": True,
        "reminders": reminders,
        "announcements": announcements,
        "pay_info": get_pay_info() if any(r["type"] == "fees" for r in reminders) else "",
    })
