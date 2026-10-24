import re
from datetime import date, datetime, timezone

from flask import Blueprint, current_app, request, jsonify

from app import db
from app.mailer import MailError, build_trial_training_email, send_email
from app.auth import admin_required
from app.models import Registration

registration_bp = Blueprint("registration", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@registration_bp.post("/registration")
def create_registration():
    data = request.get_json(silent=True) or request.form

    errors = {}
    child_name = (data.get("child") or "").strip()
    parent_name = (data.get("parent") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    age_raw = data.get("age")

    if not child_name:
        errors["child"] = "Моля, въведете име на детето."
    if not parent_name:
        errors["parent"] = "Моля, въведете име на родител."
    if not phone:
        errors["phone"] = "Моля, въведете телефон."
    if not email or not EMAIL_RE.match(email):
        errors["email"] = "Моля, въведете валиден email."

    try:
        age = int(age_raw)
        if not (4 <= age <= 18):
            errors["age"] = "Възрастта трябва да е между 4 и 18."
    except (TypeError, ValueError):
        age = None
        errors["age"] = "Моля, въведете валидна възраст."

    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    registration = Registration(
        child_name=child_name,
        child_age=age,
        parent_name=parent_name,
        phone=phone,
        email=email,
    )
    db.session.add(registration)
    db.session.commit()

    # TODO: send a confirmation/notification email here once SMTP
    # credentials for the superhosting.bg mailbox are available.

    return jsonify({"ok": True, "registration": registration.to_dict()}), 201


@registration_bp.get("/registration")
@admin_required
def list_registrations():
    """Listing for the admin table (personal data of children/parents: login required)."""
    registrations = Registration.query.order_by(Registration.created_at.desc()).all()
    return jsonify({"ok": True, "registrations": [r.to_dict() for r in registrations]})


@registration_bp.patch("/registration/<int:registration_id>")
@admin_required
def update_registration(registration_id):
    """Admin-only fields: training day, training time, processed flag."""
    registration = db.session.get(Registration, registration_id)
    if registration is None:
        return jsonify({"ok": False, "error": "Записът не е намерен."}), 404

    data = request.get_json(silent=True) or {}
    errors = {}

    if "training_date" in data:
        raw = (data["training_date"] or "").strip() if isinstance(data["training_date"], str) or data["training_date"] is None else None
        if raw is None:
            errors["training_date"] = "Невалидна дата."
        elif raw == "":
            registration.training_date = None
        else:
            try:
                registration.training_date = date.fromisoformat(raw)
            except ValueError:
                errors["training_date"] = "Невалидна дата."

    if "training_time" in data:
        raw = (data["training_time"] or "").strip() if isinstance(data["training_time"], str) or data["training_time"] is None else None
        if raw is None:
            errors["training_time"] = "Невалиден час."
        elif raw == "":
            registration.training_time = None
        else:
            try:
                registration.training_time = datetime.strptime(raw[:5], "%H:%M").time()
            except ValueError:
                errors["training_time"] = "Невалиден час."

    if "processed" in data:
        if isinstance(data["processed"], bool):
            registration.processed = data["processed"]
        else:
            errors["processed"] = "Невалидна стойност."

    if errors:
        db.session.rollback()
        return jsonify({"ok": False, "errors": errors}), 400

    db.session.commit()
    return jsonify({"ok": True, "registration": registration.to_dict()})


@registration_bp.post("/registration/<int:registration_id>/notify")
@admin_required
def notify_parent(registration_id):
    """Emails the parent the trial-training day/time. Admin-only (no auth yet)."""
    registration = db.session.get(Registration, registration_id)
    if registration is None:
        return jsonify({"ok": False, "error": "Записът не е намерен."}), 404

    if not registration.training_date or not registration.training_time:
        return jsonify({
            "ok": False,
            "error": "Първо задайте ден и час на тренировката.",
        }), 400

    subject, body = build_trial_training_email(registration)
    try:
        sent = send_email(registration.email, subject, body)
    except MailError:
        current_app.logger.exception("Could not send email for registration %s", registration_id)
        return jsonify({
            "ok": False,
            "error": "Имейлът не можа да бъде изпратен. Опитайте отново.",
        }), 502

    if sent:
        registration.notified_at = datetime.now(timezone.utc)
        db.session.commit()

    return jsonify({"ok": True, "sent": sent, "registration": registration.to_dict()})
