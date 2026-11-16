"""Такси: месеци, суми в евро, създаване на редове за плащане, обобщения, история.

Системата НЕ налага правила (отстъпки, лятна пауза и т.н.) — само създава редовете: за всеки месец от началния
до текущия, със сумата от присвояването. Всичко останало решава главният треньор."""
from datetime import date
from decimal import Decimal, InvalidOperation

from app import db
from app.match_utils import MONTHS_BG, today_sofia
from app.models import (
    FEE_MONTHLY, FEE_ONE_TIME, FEE_PAID, FEE_UNPAID, FEE_WAIVED, PLAYER_ACTIVE, FeeAssignment, FeeCharge,
    FeeHistory, PortalText,
)

CURRENCY = "€"
MAX_AMOUNT_CENTS = 10_000_000
MAX_MONTHS_AHEAD = 12
STATUS_LABELS = {FEE_UNPAID: "Неплатено", FEE_PAID: "Платено", FEE_WAIVED: "Освободено"}
PAY_INFO_KEY = "fees_pay_info"


# ---------------------------------------------------------------- месеци ---
def current_month():
    return month_start(today_sofia())


def month_start(day):
    return date(day.year, day.month, 1)


def add_months(month, n):
    index = month.year * 12 + (month.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)


def parse_month(value):
    """date (първо число) от „ГГГГ-ММ“; ValueError при грешка."""
    if not isinstance(value, str):
        raise ValueError
    year, mon = value.strip()[:7].split("-")
    month = date(int(year), int(mon), 1)
    if not 2020 <= month.year <= 2100:
        raise ValueError
    return month


def month_key(month):
    return month.strftime("%Y-%m")


def month_label(month):
    return f"{MONTHS_BG[month.month]} {month.year}"


# ----------------------------------------------------------------- пари ---
def parse_amount(value):
    """Евро (число или текст като „30“, „30.5“, „30,50“) -> центове; ValueError при грешка."""
    if isinstance(value, bool) or value is None:
        raise ValueError
    try:
        euros = Decimal(str(value).strip().replace(",", ".").replace("€", "").strip())
    except InvalidOperation:
        raise ValueError from None
    cents = int((euros * 100).to_integral_value())
    if cents < 0 or cents > MAX_AMOUNT_CENTS or (euros * 100) != (euros * 100).to_integral_value():
        raise ValueError
    return cents


def money(cents):
    """„30 €“ или „30,50 €“."""
    euros, rest = divmod(int(cents), 100)
    return f"{euros} {CURRENCY}" if rest == 0 else f"{euros},{rest:02d} {CURRENCY}"


def euros(cents):
    """Число за формите: 30 или 30.5."""
    return cents / 100 if cents % 100 else cents // 100


# ------------------------------------------------------------ редове ---
def generates(player):
    """Създават ли се нови месеци за този играч (само активен и неархивиран)."""
    return (not player.archived) and player.status == PLAYER_ACTIVE


def ensure_charges(assignment, upto=None):
    """Създава липсващите редове на присвояването до месец `upto` (по подразбиране — текущия).
    Еднократната такса е един ред в месеца си. Извикващият прави commit. Връща броя нови редове."""
    upto = upto or current_month()
    existing = {c.month for c in assignment.charges}
    created = 0

    def add(month, cents):
        nonlocal created
        db.session.add(FeeCharge(assignment=assignment, player_id=assignment.player_id,
                                 fee_type_id=assignment.fee_type_id, month=month, amount_cents=cents))
        created += 1

    if assignment.fee_type.kind == FEE_ONE_TIME:
        if assignment.start_month not in existing:
            add(assignment.start_month, assignment.first_month_amount_cents
                if assignment.first_month_amount_cents is not None else assignment.amount_cents)
        return created
    if not generates(assignment.player):
        return 0
    last = min(upto, assignment.end_month) if assignment.end_month else upto
    month = assignment.start_month
    while month <= last:
        if month not in existing:
            first = month == assignment.start_month and assignment.first_month_amount_cents is not None
            add(month, assignment.first_month_amount_cents if first else assignment.amount_cents)
        month = add_months(month, 1)
    return created


def ensure_player(player, upto=None):
    created = 0
    for assignment in player.fee_assignments:
        created += ensure_charges(assignment, upto)
    return created


def ensure_all(upto=None):
    """Всички присвоявания на активни играчи до месеца `upto`."""
    created = 0
    for assignment in FeeAssignment.query.all():
        created += ensure_charges(assignment, upto)
    return created


# ------------------------------------------------------------ обобщения ---
def _monthly(charges):
    return sorted((c for c in charges if c.fee_type.kind == FEE_MONTHLY), key=lambda c: (c.month, c.id))


def due_charges(charges, today_month=None):
    """Неплатените редове, които вече са дължими (месецът е настъпил)."""
    today_month = today_month or current_month()
    return sorted((c for c in charges if c.status == FEE_UNPAID and c.month <= today_month),
                  key=lambda c: (c.month, c.id))


def paid_until(charges):
    """Последният месец, до който всички месечни такси са платени или освободени (непрекъснато от началото);
    None, ако първият месец още е неплатен или няма месечни такси."""
    monthly = _monthly(charges)
    if not monthly:
        return None
    last = None
    for charge in monthly:
        if charge.status == FEE_UNPAID:
            break
        last = charge.month
    return last


def player_summary(player, today_month=None):
    """Обобщение за списъка „Футболисти“ и профила на детето."""
    charges = FeeCharge.query.filter_by(player_id=player.id).all()
    due = due_charges(charges, today_month)
    until = paid_until(charges)
    return {
        "has_fees": bool(player.fee_assignments),
        "paid_until": month_key(until) if until else None,
        "paid_until_text": month_label(until) if until else None,
        "unpaid_count": len(due),
        "unpaid_total_cents": sum(c.amount_cents for c in due),
        "unpaid_total_text": money(sum(c.amount_cents for c in due)),
        "unpaid_months": [month_label(c.month) for c in due if c.fee_type.kind == FEE_MONTHLY],
    }


def charge_label(charge):
    if charge.fee_type.kind == FEE_ONE_TIME:
        return charge.fee_type.name
    return f"{charge.fee_type.name} — {month_label(charge.month)}"


# ------------------------------------------------------------- история ---
def log(player_id, action, detail, by, charge=None, assignment=None):
    db.session.add(FeeHistory(player_id=player_id, charge_id=charge.id if charge is not None else None,
                              assignment_id=assignment.id if assignment is not None else None,
                              action=action, detail=detail[:300], by=by[:80]))


def get_pay_info():
    row = db.session.get(PortalText, PAY_INFO_KEY)
    return row.value if row is not None else ""
