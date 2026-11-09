"""Магазин: отчети (оборот, най-продавани), CSV експорт и почистване на стари поръчки.

Периодите са по календарни дни по софийско време (включително от и до). В базата времената са в UTC,
затова границите на деня се превръщат в UTC. Експортът е с „;“ за разделител и UTF-8 с BOM,
за да се отваря правилно в български Excel (кирилица, десетична запетая).
"""
import calendar
import csv
import io
from datetime import date, datetime, timedelta, timezone

from app.models import (
    DELIVERY_ADDRESS, ORDER_CANCELLED, ORDER_DELIVERED, ORDER_NEW, ORDER_PROCESSED, Order,
)

STATUS_LABELS = {
    ORDER_NEW: "Нова", ORDER_PROCESSED: "Обработена", ORDER_DELIVERED: "Предадена", ORDER_CANCELLED: "Отказана",
}
SCOPE_CONFIRMED = "confirmed"   # обработени + предадени (потвърдените от треньора)
SCOPE_ALL = "all"               # всички без отказаните (включва и още необработените нови)
SCOPES = {
    SCOPE_CONFIRMED: (ORDER_PROCESSED, ORDER_DELIVERED),
    SCOPE_ALL: (ORDER_NEW, ORDER_PROCESSED, ORDER_DELIVERED),
}
TOP_ITEMS = 15


# ------------------------------------------------------------- време ---
def _sofia():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Sofia")
    except Exception:  # няма tz база данни (Windows без пакета tzdata) — приблизително EET
        return None


def local_day_start_utc(day):
    """Началото на деня по софийско време като наивен UTC (така е в базата)."""
    tz = _sofia()
    if tz is not None:
        return datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    return datetime(day.year, day.month, day.day) - timedelta(hours=2)


def to_local(naive_utc):
    tz = _sofia()
    if tz is not None:
        return naive_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    return naive_utc + timedelta(hours=2)


def today_local():
    return to_local(datetime.now(timezone.utc).replace(tzinfo=None)).date()


def subtract_months(day, months):
    year, month = day.year, day.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def parse_day(text):
    """„2026-11-05“ -> date; празно -> None; ValueError при друг формат."""
    text = (text or "").strip()
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d").date()


def period_bounds(date_from, date_to):
    """(начало, край) като наивен UTC; край е изключен. None = без ограничение от тази страна."""
    start = local_day_start_utc(date_from) if date_from else None
    end = local_day_start_utc(date_to + timedelta(days=1)) if date_to else None
    return start, end


def orders_in_period(date_from, date_to, statuses=None):
    start, end = period_bounds(date_from, date_to)
    query = Order.query
    if start:
        query = query.filter(Order.created_at >= start)
    if end:
        query = query.filter(Order.created_at < end)
    if statuses:
        query = query.filter(Order.status.in_(statuses))
    return query.order_by(Order.created_at, Order.id).all()


# ---------------------------------------------------------- статистика ---
def build_stats(date_from, date_to, scope):
    """Оборот и най-продавани артикули за период. Отказаните никога не се броят в оборота."""
    counted = SCOPES[scope]
    orders = orders_in_period(date_from, date_to)
    by_status = {status: 0 for status in STATUS_LABELS}
    revenue = pending = 0
    counted_orders = 0
    top = {}
    pieces = 0
    for order in orders:
        by_status[order.status] = by_status.get(order.status, 0) + 1
        if order.status == ORDER_NEW:
            pending += order.total_cents
        if order.status not in counted:
            continue
        counted_orders += 1
        revenue += order.total_cents
        for item in order.items:
            row = top.setdefault(item.product_name, {"name": item.product_name, "qty": 0, "revenue_cents": 0, "personalized": 0})
            row["qty"] += item.qty
            row["revenue_cents"] += item.line_total_cents
            if item.personal_name or item.personal_number:
                row["personalized"] += item.qty
            pieces += item.qty
    ranked = sorted(top.values(), key=lambda r: (-r["qty"], -r["revenue_cents"], r["name"]))
    return {
        "orders_total": len(orders),
        "by_status": by_status,
        "counted_orders": counted_orders,
        "revenue_cents": revenue,
        "average_cents": round(revenue / counted_orders) if counted_orders else 0,
        "pending_new_cents": pending,   # сума на още необработените нови поръчки
        "pieces": pieces,
        "top_items": [
            {"name": r["name"], "qty": r["qty"], "revenue_cents": r["revenue_cents"], "personalized": r["personalized"]}
            for r in ranked[:TOP_ITEMS]
        ],
        "top_items_more": max(0, len(ranked) - TOP_ITEMS),
    }


# ----------------------------------------------------------------- CSV ---
def _money(cents):
    return f"{cents // 100},{cents % 100:02d}"


def _safe(value):
    """Защита от формули в Excel: клетка, започваща с = + - @, се предхожда от апостроф."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


CSV_HEADER = [
    "Номер на поръчка", "Дата и час", "Статус", "Клиент", "Телефон", "Имейл", "Получаване", "Адрес",
    "Артикул", "Размер", "Размерна група", "Брой", "Единична цена (€)", "Доплащане за персонализация на брой (€)",
    "Име за печат", "Номер за печат", "Сума на реда (€)", "Обща сума на поръчката (€)", "Бележка",
]


def build_csv(orders):
    """Един ред за всеки артикул от поръчка. Общата сума е само на първия ред на поръчката,
    за да не се удвоява при събиране в Excel."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for order in orders:
        when = to_local(order.created_at).strftime("%d.%m.%Y %H:%M") if order.created_at else ""
        delivery = "Доставка до адрес" if order.delivery == DELIVERY_ADDRESS else "От академията"
        for index, item in enumerate(order.items):
            writer.writerow([_safe(v) for v in [
                order.number, when, STATUS_LABELS.get(order.status, order.status), order.customer_name, order.phone,
                order.email, delivery, order.address, item.product_name,
                "един размер" if not item.group_label else item.size, item.group_label, item.qty,
                _money(item.unit_price_cents), _money(item.personalization_fee_cents) if item.personalization_fee_cents else "",
                item.personal_name, item.personal_number, _money(item.line_total_cents),
                _money(order.total_cents) if index == 0 else "", order.admin_note if index == 0 else "",
            ]])
    return "\ufeff" + out.getvalue()


# --------------------------------------------------------- почистване ---
def purge_cutoff(months):
    """Дата, преди която (по софийско време) поръчките се смятат за стари."""
    return subtract_months(today_local(), months)


def old_orders(months):
    cutoff = purge_cutoff(months)
    return cutoff, Order.query.filter(Order.created_at < local_day_start_utc(cutoff)).order_by(Order.created_at).all()
