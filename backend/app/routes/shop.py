"""Магазин на академията — админ API за артикулите.

Админ:  GET    /api/admin/shop/products              всички артикули (и скритите) + размери по подразбиране
        POST   /api/admin/shop/products              нов артикул
        PATCH  /api/admin/shop/products/<id>         промяна (приема и само част от полетата)
        DELETE /api/admin/shop/products/<id>         изтриване (трие и снимката)
        POST   /api/admin/shop/products/<id>/move    {"direction": "up" | "down"} — подредба

Публично: GET /shop                 магазинът (артикули, избор на размер, количка в браузъра)
          GET /privacy              политика за обработване на лични данни
          POST /api/shop/orders     изпращане на поръчка (записва се + два имейла: до клиента и до главния треньор)

Админ — поръчки:
        GET    /api/admin/shop/orders?status=&q=      списък (най-новите първи) + брой по статуси
        GET    /api/admin/shop/orders/summary         {"new": n} — нови поръчки (за значката в менюто)
        PATCH  /api/admin/shop/orders/<id>            {"status": ..., "admin_note": ...}
        POST   /api/admin/shop/orders/<id>/resend     {"to": "coach" | "customer"} — повторно изпращане на имейл
        DELETE /api/admin/shop/orders/<id>            само главен админ (изтрива личните данни)

Админ — отчети (период по софийско време, дати във вид 2026-11-05; празно = без ограничение):
        GET    /api/admin/shop/reports/stats?from=&to=&scope=confirmed|all   оборот и най-продавани артикули
        GET    /api/admin/shop/orders/export?from=&to=                        CSV файл (за Excel)
        GET    /api/admin/shop/orders/purge-preview?months=12                 колко поръчки са по-стари (само главен админ)
        POST   /api/admin/shop/orders/purge   {"months": 12, "expected": n}   изтрива старите поръчки (само главен админ)

Достъп до админ частта: главен админ и главен треньор. Обикновените треньори не виждат магазина.
"""
from flask import Blueprint, Response, current_app, jsonify, render_template, request

from app import db
from app.auth import check_admin, current_user
from app.models import (
    ADULT_SIZES, CHILD_SIZES, DEFAULT_PERSONALIZATION_FEE_CENTS, ONE_SIZE_LABEL, ORDER_NEW, ORDER_STATUSES, Order, Product,
)
from app.routes.news import DEFAULT_SHARE_IMAGE, _absolute
from app import shop_reports as reports
from app.shop_orders import (
    create_order, notify, rate_limited, send_coach_email, send_customer_email, validate_order,
)
from app.shop_utils import (
    apply_cleaned, current_values, next_sort_order, public_products, remove_image_files, validate_product,
)

admin_shop_bp = Blueprint("admin_shop", __name__)
page_bp = Blueprint("shop_page", __name__)
shop_api_bp = Blueprint("shop_api", __name__)

FIELDS = ("name", "size_mode", "price_child", "price_adult", "allows_personalization",
          "personalization_fee", "sold_out_sizes", "image", "is_visible")


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def _who():
    user = current_user()
    return (user.display_name or user.username) if user else ""


@admin_shop_bp.before_request
def _shop_access():
    denied = check_admin()
    if denied is not None:
        return denied
    user = current_user()
    if not (user.is_owner or user.is_head_coach):
        return _error("Магазинът се управлява от главния админ и главния треньор.", 403)
    return None


@page_bp.get("/shop")
@page_bp.get("/shop/")
def shop_page():
    products = public_products()
    # Снимката на първия артикул е най-добрата картинка за споделяне във Facebook.
    first_image = next((p["image"] for p in products if p["image"]), None)
    return render_template(
        "shop_page.html",
        products=products,
        page_url=_absolute("/shop"),
        image_url=_absolute(first_image or DEFAULT_SHARE_IMAGE),
    )


@page_bp.get("/privacy")
@page_bp.get("/privacy/")
def privacy_page():
    return render_template("privacy_page.html", page_url=_absolute("/privacy"), image_url=_absolute(DEFAULT_SHARE_IMAGE))


@shop_api_bp.post("/shop/orders")
def submit_order():
    """Приема поръчка. Цените се смятат на сървъра; при успех — запис + имейли."""
    payload = request.get_json(silent=True)
    if isinstance(payload, dict) and payload.get("website"):
        # Скритото поле „website“ го попълват само ботове: правим се, че е минало, без да записваме.
        return jsonify({"ok": True, "order": {"number": "000000-000", "total": 0}}), 201
    if rate_limited(request.remote_addr or "?"):
        return _error("Изпратени са твърде много поръчки. Опитайте пак след няколко минути.", 429)

    customer, lines, errors, item_error = validate_order(payload)
    if errors:
        return jsonify({"ok": False, "errors": errors, "error": errors.get("_")}), 400
    if item_error:
        return _error(item_error, 409)

    order = create_order(customer, lines)
    try:
        notify(order)
    except Exception:  # пощата никога не бива да губи вече записаната поръчка
        current_app.logger.exception("Поръчка %s: грешка при изпращане на имейлите.", order.number)
    return jsonify({"ok": True, "order": {"number": order.number, "total": order.total_cents / 100}}), 201


def _ordered():
    return Product.query.order_by(Product.sort_order, Product.id).all()


@admin_shop_bp.get("/admin/shop/products")
def list_products():
    return jsonify({
        "ok": True,
        "products": [p.to_dict() for p in _ordered()],
        "meta": {
            "child_sizes": CHILD_SIZES,
            "adult_sizes": ADULT_SIZES,
            "one_size_label": ONE_SIZE_LABEL,
            "default_fee": DEFAULT_PERSONALIZATION_FEE_CENTS // 100,
        },
    })


@admin_shop_bp.post("/admin/shop/products")
def create_product():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    cleaned, errors = validate_product({k: data[k] for k in FIELDS if k in data})
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    product = Product(sort_order=next_sort_order(), created_by=_who(), updated_by=_who())
    apply_cleaned(product, cleaned)
    db.session.add(product)
    db.session.commit()
    return jsonify({"ok": True, "product": product.to_dict()}), 201


@admin_shop_bp.patch("/admin/shop/products/<int:product_id>")
def update_product(product_id):
    product = db.session.get(Product, product_id)
    if product is None:
        return _error("Артикулът не е намерен.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    values = current_values(product)
    values.update({k: data[k] for k in FIELDS if k in data})
    cleaned, errors = validate_product(values)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    old_image = product.image
    apply_cleaned(product, cleaned)
    product.updated_by = _who()
    db.session.commit()
    if old_image and old_image != product.image:
        remove_image_files(old_image)  # заменена или махната снимка — файловете се чистят
    return jsonify({"ok": True, "product": product.to_dict()})


@admin_shop_bp.delete("/admin/shop/products/<int:product_id>")
def delete_product(product_id):
    product = db.session.get(Product, product_id)
    if product is None:
        return _error("Артикулът не е намерен.", 404)
    image = product.image
    db.session.delete(product)
    db.session.commit()
    if image:
        remove_image_files(image)
    return jsonify({"ok": True})


@admin_shop_bp.post("/admin/shop/products/<int:product_id>/move")
def move_product(product_id):
    data = request.get_json(silent=True) or {}
    direction = data.get("direction")
    if direction not in ("up", "down"):
        return _error("Невалидна заявка.")
    items = _ordered()
    index = next((i for i, p in enumerate(items) if p.id == product_id), None)
    if index is None:
        return _error("Артикулът не е намерен.", 404)
    target = index - 1 if direction == "up" else index + 1
    if 0 <= target < len(items):
        items[index], items[target] = items[target], items[index]
    for position, product in enumerate(items, start=1):  # преномерира всичко, за да няма дублиращи се номера
        product.sort_order = position
    db.session.commit()
    return jsonify({"ok": True, "products": [p.to_dict() for p in items]})


# ------------------------------------------------------------- поръчки ---
MAX_ORDERS_SHOWN = 300
MAX_NOTE = 2000


def _status_counts():
    counts = {status: 0 for status in ORDER_STATUSES}
    for status, count in db.session.query(Order.status, db.func.count(Order.id)).group_by(Order.status).all():
        counts[status] = count
    return counts


@admin_shop_bp.get("/admin/shop/orders/summary")
def orders_summary():
    return jsonify({"ok": True, "new": Order.query.filter_by(status=ORDER_NEW).count()})


@admin_shop_bp.get("/admin/shop/orders")
def list_orders():
    query = Order.query
    status = request.args.get("status", "").strip()
    if status in ORDER_STATUSES:
        query = query.filter(Order.status == status)
    text = request.args.get("q", "").strip()[:80]
    if text:
        like = f"%{text}%"
        query = query.filter(db.or_(
            Order.number.ilike(like), Order.customer_name.ilike(like), Order.phone.ilike(like), Order.email.ilike(like),
        ))
    total = query.count()
    orders = query.order_by(Order.created_at.desc(), Order.id.desc()).limit(MAX_ORDERS_SHOWN).all()
    return jsonify({
        "ok": True,
        "orders": [o.to_dict() for o in orders],
        "matching": total,
        "shown_all": total <= MAX_ORDERS_SHOWN,
        "counts": _status_counts(),
    })


@admin_shop_bp.patch("/admin/shop/orders/<int:order_id>")
def update_order(order_id):
    order = db.session.get(Order, order_id)
    if order is None:
        return _error("Поръчката не е намерена.", 404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Невалидна заявка.")
    if "status" in data:
        if data["status"] not in ORDER_STATUSES:
            return _error("Невалиден статус.")
        order.status = data["status"]
    if "admin_note" in data:
        note = data["admin_note"]
        if not isinstance(note, str) or len(note) > MAX_NOTE:
            return _error(f"Бележката е твърде дълга (до {MAX_NOTE} знака).")
        order.admin_note = note.strip()
    db.session.commit()
    return jsonify({"ok": True, "order": order.to_dict(), "counts": _status_counts()})


@admin_shop_bp.post("/admin/shop/orders/<int:order_id>/resend")
def resend_order_email(order_id):
    order = db.session.get(Order, order_id)
    if order is None:
        return _error("Поръчката не е намерена.", 404)
    target = (request.get_json(silent=True) or {}).get("to")
    if target not in ("coach", "customer"):
        return _error("Невалидна заявка.")
    sent = send_coach_email(order) if target == "coach" else send_customer_email(order)
    if not sent:
        return jsonify({"ok": False, "error": "Имейлът пак не можа да бъде изпратен. Проверете настройките на пощата.",
                        "order": order.to_dict()}), 502
    return jsonify({"ok": True, "order": order.to_dict()})


@admin_shop_bp.delete("/admin/shop/orders/<int:order_id>")
def delete_order(order_id):
    if not current_user().is_owner:
        return _error("Поръчките се изтриват само от главния админ.", 403)
    order = db.session.get(Order, order_id)
    if order is None:
        return _error("Поръчката не е намерена.", 404)
    db.session.delete(order)
    db.session.commit()
    return jsonify({"ok": True, "counts": _status_counts()})


# ------------------------------------------------------------- отчети ---
PURGE_MONTHS = (3, 6, 12, 24)


def _period():
    """(от, до, грешка) от параметрите ?from=&to= (по желание)."""
    try:
        date_from = reports.parse_day(request.args.get("from"))
        date_to = reports.parse_day(request.args.get("to"))
    except ValueError:
        return None, None, "Невалидна дата. Използвайте формат ГГГГ-ММ-ДД."
    if date_from and date_to and date_from > date_to:
        return None, None, "Началната дата е след крайната."
    return date_from, date_to, None


@admin_shop_bp.get("/admin/shop/reports/stats")
def reports_stats():
    date_from, date_to, error = _period()
    if error:
        return _error(error)
    scope = request.args.get("scope", reports.SCOPE_CONFIRMED)
    if scope not in reports.SCOPES:
        return _error("Невалиден избор на поръчки за отчета.")
    stats = reports.build_stats(date_from, date_to, scope)

    def euros(cents):
        return cents // 100 if cents % 100 == 0 else cents / 100

    return jsonify({
        "ok": True,
        "scope": scope,
        "orders_total": stats["orders_total"],
        "by_status": stats["by_status"],
        "counted_orders": stats["counted_orders"],
        "revenue": euros(stats["revenue_cents"]),
        "average": euros(stats["average_cents"]),
        "pending_new": euros(stats["pending_new_cents"]),
        "pieces": stats["pieces"],
        "top_items": [
            {"name": i["name"], "qty": i["qty"], "revenue": euros(i["revenue_cents"]), "personalized": i["personalized"]}
            for i in stats["top_items"]
        ],
        "top_items_more": stats["top_items_more"],
    })


@admin_shop_bp.get("/admin/shop/orders/export")
def export_orders():
    date_from, date_to, error = _period()
    if error:
        return _error(error)
    orders = reports.orders_in_period(date_from, date_to)
    name = "porachki-" + (str(date_from) if date_from else "nachalo") + "_" + (str(date_to) if date_to else "dnes") + ".csv"
    current_app.logger.info("Експорт на %d поръчки (%s) от %s.", len(orders), name, _who())
    return Response(
        reports.build_csv(orders),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


def _owner_only():
    if not current_user().is_owner:
        return _error("Почистването на стари поръчки е само за главния админ.", 403)
    return None


def _months():
    try:
        months = int(request.args.get("months") if request.method == "GET" else (request.get_json(silent=True) or {}).get("months"))
    except (TypeError, ValueError):
        return None
    return months if months in PURGE_MONTHS else None


@admin_shop_bp.get("/admin/shop/orders/purge-preview")
def purge_preview():
    denied = _owner_only()
    if denied:
        return denied
    months = _months()
    if months is None:
        return _error("Изберете период: " + ", ".join(str(m) for m in PURGE_MONTHS) + " месеца.")
    cutoff, old = reports.old_orders(months)
    by_status = {}
    for order in old:
        by_status[order.status] = by_status.get(order.status, 0) + 1
    return jsonify({
        "ok": True, "months": months, "cutoff": str(cutoff), "count": len(old), "by_status": by_status,
        "export_to": str(cutoff - reports.timedelta(days=1)),
    })


@admin_shop_bp.post("/admin/shop/orders/purge")
def purge_orders():
    denied = _owner_only()
    if denied:
        return denied
    months = _months()
    data = request.get_json(silent=True) or {}
    if months is None or not isinstance(data.get("expected"), int):
        return _error("Невалидна заявка.")
    cutoff, old = reports.old_orders(months)
    if len(old) != data["expected"]:
        return _error(f"Броят на старите поръчки се промени ({len(old)}). Прегледайте отново, преди да изтриете.", 409)
    for order in old:
        db.session.delete(order)
    db.session.commit()
    current_app.logger.warning("Изтрити %d поръчки, по-стари от %s (%d месеца), от %s.", len(old), cutoff, months, _who())
    return jsonify({"ok": True, "deleted": len(old), "counts": _status_counts()})
