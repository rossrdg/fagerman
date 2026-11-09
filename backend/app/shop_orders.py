"""Поръчки от магазина: проверка на данните, изчисляване на цените на сървъра, номер, имейли.

Браузърът праща само кой артикул, кой размер и колко броя; цените винаги се четат наново от
базата. Всичко, което клиентът въведе, се чисти от управляващи знаци (защита на имейл заглавията).
"""
import re
import threading
import time
from datetime import datetime

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app import db
from app.mailer import MailError, send_email
from app.models import DELIVERY_ADDRESS, DELIVERY_MODES, DELIVERY_PICKUP, Order, OrderItem, Product, utcnow
from app.shop_utils import format_eur, price_for_size

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_LINES = 30
MAX_QTY = 10
MAX_PERSONAL_NAME = 14
PERSONAL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]*$")  # латиница: започва с буква, после букви, интервал, . ' -
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value, limit):
    """Текст -> без управляващи знаци, със сбити интервали; None при нетекст."""
    if not isinstance(value, str):
        return None
    return re.sub(r"\s+", " ", CONTROL_CHARS.sub(" ", value)).strip()[:limit + 1]


def clean_personalization(raw):
    """Име и номер за печат -> (име, номер, грешка). Името се записва с ГЛАВНИ букви, номерът е 1–99.

    Празно е позволено (няма персонализация); попълнено поне едно от двете = персонализация.
    """
    if raw in (None, "", {}):
        return "", "", None
    if not isinstance(raw, dict):
        return "", "", "Невалидна персонализация."
    name = _clean(raw.get("name") or "", MAX_PERSONAL_NAME) or ""
    number = _clean(str(raw.get("number") if raw.get("number") is not None else ""), 3) or ""
    if name:
        if len(name) > MAX_PERSONAL_NAME:
            return "", "", f"Името за персонализация е до {MAX_PERSONAL_NAME} знака."
        if not PERSONAL_NAME_RE.match(name):
            return "", "", "Името за персонализация трябва да е на латиница (A–Z)."
        name = name.upper()
    if number:
        if not re.fullmatch(r"\d{1,2}", number) or not (1 <= int(number) <= 99):
            return "", "", "Номерът за персонализация трябва да е от 1 до 99."
        number = str(int(number))
    return name, number, None


# ------------------------------------------------------------ защита ---
_hits = {}
_hits_lock = threading.Lock()


def rate_limited(key):
    """True, ако от този адрес има твърде много поръчки напоследък (в паметта на процеса)."""
    limit = current_app.config["SHOP_ORDER_LIMIT"]
    window = current_app.config["SHOP_ORDER_WINDOW_SECONDS"]
    now = time.monotonic()
    with _hits_lock:
        recent = [t for t in _hits.get(key, []) if now - t < window]
        if len(recent) >= limit:
            _hits[key] = recent
            return True
        recent.append(now)
        _hits[key] = recent
        return False


# ------------------------------------------------------------ проверка ---
def validate_order(payload):
    """Връща (customer, lines, errors, item_error).

    errors     — грешки по полетата на формата (400);
    item_error — текст, ако нещо в количката вече не е налично (409).
    """
    errors, customer, lines, item_error = {}, {}, [], None
    if not isinstance(payload, dict):
        return customer, lines, {"_": "Невалидна заявка."}, None
    data = payload.get("customer")
    data = data if isinstance(data, dict) else {}

    name = _clean(data.get("name"), 100)
    if not name or len(name) < 2:
        errors["name"] = "Въведете име."
    elif len(name) > 100:
        errors["name"] = "Името е твърде дълго."
    customer["name"] = name or ""

    email = _clean(data.get("email"), 150)
    if not email or not EMAIL_RE.match(email) or len(email) > 150:
        errors["email"] = "Въведете валиден имейл адрес."
    customer["email"] = email or ""

    phone = _clean(data.get("phone"), 40)
    digits = re.sub(r"\D", "", phone or "")
    if not phone or not re.fullmatch(r"\+?[\d\s\-()/.]+", phone) or not (6 <= len(digits) <= 15):
        errors["phone"] = "Въведете валиден телефон, напр. 0888 123 456."
    customer["phone"] = phone or ""

    delivery = data.get("delivery") or DELIVERY_PICKUP
    if delivery not in DELIVERY_MODES:
        errors["delivery"] = "Изберете начин на получаване."
        delivery = DELIVERY_PICKUP
    customer["delivery"] = delivery

    address = ""
    if delivery == DELIVERY_ADDRESS:
        address = _clean(data.get("address"), 300) or ""
        if len(address) > 300:
            errors["address"] = "Адресът е твърде дълъг (до 300 знака)."
    customer["address"] = address

    if data.get("consent") is not True:
        errors["consent"] = "Трябва да сте запознат/а с Политиката за обработване на лични данни."

    raw = payload.get("items")
    if not isinstance(raw, list) or not raw:
        return customer, lines, {**errors, "_": "Количката е празна."}, None
    if len(raw) > MAX_LINES:
        return customer, lines, {**errors, "_": "Твърде много артикули в една поръчка."}, None

    merged = {}
    for entry in raw:
        if not isinstance(entry, dict):
            return customer, lines, {**errors, "_": "Невалидна заявка."}, None
        try:
            pid, qty = int(entry.get("id")), int(entry.get("qty"))
        except (TypeError, ValueError):
            return customer, lines, {**errors, "_": "Невалидна заявка."}, None
        size = _clean(entry.get("size"), 20)
        if not size or not (1 <= qty <= MAX_QTY):
            return customer, lines, {**errors, "_": "Невалидно количество в количката."}, None
        pname, pnumber, perr = clean_personalization(entry.get("personal"))
        if perr:
            return customer, lines, {**errors, "_": perr}, None
        key = (pid, size, pname, pnumber)
        merged[key] = merged.get(key, 0) + qty
        if merged[key] > MAX_QTY:
            return customer, lines, {**errors, "_": f"Най-много {MAX_QTY} броя от един артикул и размер."}, None

    for (pid, size, pname, pnumber), qty in merged.items():
        product = db.session.get(Product, pid)
        priced = price_for_size(product, size) if product is not None and product.is_visible else None
        if priced is None or priced[0] is None:
            item_error = "Някои артикули вече не се предлагат. Презаредете страницата и проверете количката."
            break
        cents, group, sold_out = priced
        personalized = bool(pname or pnumber)
        if personalized and not product.allows_personalization:
            item_error = f"„{product.name}“ не се персонализира. Презаредете страницата и проверете количката."
            break
        if sold_out:
            item_error = f"Размер {size} на „{product.name}“ е изчерпан. Презаредете страницата и изберете друг."
            break
        lines.append({
            "product": product, "size": size, "group": group, "qty": qty, "unit": cents,
            "pname": pname, "pnumber": pnumber,
            "fee": product.personalization_fee_cents if personalized else 0,
        })
    return customer, lines, errors, item_error


# --------------------------------------------------------------- запис ---
def sofia_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Sofia"))
    except Exception:  # няма tz база данни (напр. Windows без пакета tzdata)
        return datetime.now()


def create_order(customer, lines):
    """Записва поръчката с номер ДДММГГ-001 (пореден за деня). При съвпадение на номера пробва пак."""
    prefix = f"{sofia_now():%d%m%y}"
    total = sum((l["unit"] + l["fee"]) * l["qty"] for l in lines)
    for _ in range(6):
        count = Order.query.filter(Order.number.like(f"{prefix}-%")).count()
        order = Order(
            number=f"{prefix}-{count + 1:03d}", customer_name=customer["name"], email=customer["email"],
            phone=customer["phone"], delivery=customer["delivery"], address=customer["address"],
            total_cents=total, consent_at=utcnow(),
        )
        for l in lines:
            order.items.append(OrderItem(
                product_id=l["product"].id, product_name=l["product"].name, size=l["size"],
                group_label=l["group"], unit_price_cents=l["unit"], qty=l["qty"],
                personal_name=l["pname"], personal_number=l["pnumber"], personalization_fee_cents=l["fee"],
            ))
        db.session.add(order)
        try:
            db.session.commit()
            return order
        except IntegrityError:
            db.session.rollback()
    raise RuntimeError("Не успях да създам номер на поръчка.")


# -------------------------------------------------------------- имейли ---
def _item_line(item):
    size = "един размер" if not item.group_label else f"размер {item.size} ({item.group_label.lower()})"
    line = f"  • {item.product_name} — {size} × {item.qty} — {format_eur(item.line_total_cents)} €"
    if item.personal_name or item.personal_number:
        parts = []
        if item.personal_name:
            parts.append(f"име {item.personal_name}")
        if item.personal_number:
            parts.append(f"номер {item.personal_number}")
        line += f"\n      Персонализация: {', '.join(parts)} (+{format_eur(item.personalization_fee_cents)} € на брой)"
    return line


def _delivery_text(order):
    if order.delivery == DELIVERY_ADDRESS:
        return f"Доставка до адрес: {order.address}" if order.address else "Доставка до адрес (адресът ще бъде уточнен по телефона)"
    return "Ще вземете поръчката от академията."


def build_customer_email(order):
    subject = f"Получихме поръчката Ви № {order.number} — Футболна Академия Герман"
    body = (
        f"Здравейте {order.customer_name},\n\n"
        f"Получихме Вашата поръчка № {order.number}.\n\n"
        "Поръчани артикули:\n" + "\n".join(_item_line(i) for i in order.items) + "\n\n"
        f"Общо (ориентировъчно): {format_eur(order.total_cents)} €\n"
        f"{_delivery_text(order)}\n\n"
        f"Ще се свържем с Вас по телефона ({order.phone}), за да потвърдим поръчката и да уточним "
        "начина на плащане. Цените са ориентировъчни до това потвърждение. Този имейл не е "
        "потвърждение на поръчката.\n\n"
        "Благодарим Ви!\n"
        "Футболна Академия Герман\n"
    )
    return subject, body


def build_coach_email(order):
    subject = f"Нова поръчка № {order.number} — {order.customer_name}, {format_eur(order.total_cents)} €"
    body = (
        f"Нова поръчка от магазина: № {order.number}\n\n"
        "Клиент:\n"
        f"  Име: {order.customer_name}\n"
        f"  Телефон: {order.phone}\n"
        f"  Имейл: {order.email}\n"
        f"  {_delivery_text(order)}\n\n"
        "Артикули:\n" + "\n".join(_item_line(i) for i in order.items) + "\n\n"
        f"Общо (ориентировъчно): {format_eur(order.total_cents)} €\n\n"
        "Свържете се с клиента по телефона, за да потвърдите поръчката и да уточните плащането.\n"
        "(Можете да отговорите директно на този имейл — отговорът отива при клиента.)\n"
    )
    return subject, body


def _coach_address():
    cfg = current_app.config
    return cfg.get("SHOP_ORDER_EMAIL") or cfg.get("MAIL_REPLY_TO") or cfg.get("MAIL_FROM") or cfg.get("MAIL_USERNAME")


def _attempt(order, to_addr, subject_body, reply_to=None):
    if not to_addr:
        current_app.logger.error("Поръчка %s: няма получател за имейла (SHOP_ORDER_EMAIL).", order.number)
        return False
    try:
        send_email(to_addr, *subject_body, reply_to=reply_to)
        return True
    except MailError as exc:
        current_app.logger.error("Поръчка %s: имейлът до %s не е изпратен: %s", order.number, to_addr, exc)
        return False


def send_coach_email(order):
    order.coach_notified = _attempt(order, _coach_address(), build_coach_email(order), reply_to=order.email)
    db.session.commit()
    return order.coach_notified


def send_customer_email(order):
    order.customer_notified = _attempt(order, order.email, build_customer_email(order))
    db.session.commit()
    return order.customer_notified


def notify(order):
    """Праща двата имейла и записва дали са успели. Поръчката е записана и при неуспех на пощата."""
    send_coach_email(order)
    send_customer_email(order)
