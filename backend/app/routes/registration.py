import re

from flask import Blueprint, request, jsonify

from app import db
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
    message = (data.get("message") or "").strip()
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
        message=message or None,
    )
    db.session.add(registration)
    db.session.commit()

    # TODO: send a confirmation/notification email here once SMTP
    # credentials for the superhosting.bg mailbox are available.

    return jsonify({"ok": True, "registration": registration.to_dict()}), 201


@registration_bp.get("/registration")
def list_registrations():
    """Simple listing for now (no auth yet) so you can verify data
    is being saved. Lock this down before it ever goes to production."""
    registrations = Registration.query.order_by(Registration.created_at.desc()).all()
    return jsonify({"ok": True, "registrations": [r.to_dict() for r in registrations]})
