"""Попълване на официалните бланки на БФС (заявление, декларация, медицинско) от данните на родителя.

ВАЖНО ЗА ЛИЧНИТЕ ДАННИ: всичко, което се подава тук (ЕГН, лична карта, акт за раждане, имена на родители),
живее само в паметта по време на една заявка. Тук няма запис в база, файл, лог, сесия или кеш, а
съобщенията за грешки никога не съдържат въведени стойности. Не добавяйте логове на `values`.

Бланките се попълват като текст ВЪРХУ оригиналния шаблон (текстът им не се променя). Позициите са в
bfs_templates/fields.json; шрифтът е Carlito (метрично съвместим с Calibri на бланките)."""
import io
import json
import os
import re
from datetime import datetime

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app import db
from app.documents_catalog import CAT_ADULT, CAT_MINOR, CAT_UNDER14, TEMPLATE_DIR
from app.models import Setting

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_PATH = os.path.join(BASE_DIR, "fonts", "Carlito-Regular.ttf")
FONT_NAME = "Carlito"
DEFAULT_CLUB_NAME = "ФУТБОЛЕН КЛУБ ФУТБОЛНА АКАДЕМИЯ ГЕРМАН"
CLUB_KEY = "club_name"
MAX_VALUE = 120
BASE_SIZE = 11.0   # размерът на текста в бланките
MIN_SIZE = 7.0

_FIELDS = None


class FormError(Exception):
    """Грешка във въведените данни. `errors` е {поле: съобщение} — никога със стойности."""

    def __init__(self, errors):
        super().__init__("invalid form")
        self.errors = errors


# ------------------------------------------------------ описание на формата ---
def _f(key, label, kind="text", required=True, hint=None):
    return {"key": key, "label": label, "kind": kind, "required": required, "hint": hint}


def form_groups(category):
    """Групите полета за категорията — единственият източник и за формата, и за проверката."""
    parents = [
        _f("p1_name", "Родител 1 — име, презиме и фамилия"),
        _f("p1_egn", "Родител 1 — ЕГН", "egn"),
        _f("p2_name", "Родител 2 — име, презиме и фамилия", required=False,
           hint="По желание. Бланката може да се подпише от един родител."),
        _f("p2_egn", "Родител 2 — ЕГН", "egn", required=False),
    ]
    place = [
        _f("city", "Град (където се подписва)"),
        _f("date", "Дата", "date"),
    ]
    if category == CAT_UNDER14:
        return [
            {"title": "Родители / настойници", "fields": parents},
            {"title": "Детето", "fields": [
                _f("child_bg", "Имена на детето (на кирилица)"),
                _f("child_lat", "Имена на детето (на латиница)", "latin"),
                _f("child_egn", "ЕГН на детето", "egn"),
                _f("birth_cert_no", "№ на акта за раждане", "idno"),
            ]},
            {"title": "Място и дата", "fields": place},
        ]
    player = [
        _f("player_bg", "Имена на състезателя (на кирилица)"),
        _f("player_lat", "Имена на състезателя (на латиница)", "latin"),
        _f("player_egn", "ЕГН на състезателя", "egn"),
    ]
    identity = [
        _f("id_no", "№ на личната карта", "idno"),
        _f("id_date", "Издадена на", "date"),
        _f("id_issuer", "Издадена от МВР — град", hint="Само мястото, напр. „София“ (в бланката вече пише „от МВР“)."),
    ]
    if category == CAT_MINOR:
        return [
            {"title": "Състезателят", "fields": player + identity},
            {"title": "Родители / настойници", "fields": parents},
            {"title": "Място и дата", "fields": place},
        ]
    return [
        {"title": "Състезателят", "fields": player + identity},
        {"title": "Място и дата", "fields": place},
    ]


def _all_fields(category):
    return [f for g in form_groups(category) for f in g["fields"]]


# ---------------------------------------------------------------- проверка ---
def _clean(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def validate(category, raw):
    """Проверени и изчистени стойности. Грешка -> FormError. Нищо не се записва.
    ЕГН се проверява само за формат (10 цифри) — без контролна цифра и сравнение с датата на раждане."""
    raw = raw if isinstance(raw, dict) else {}
    errors, values = {}, {}
    for f in _all_fields(category):
        key, kind = f["key"], f["kind"]
        value = _clean(raw.get(key))
        if key.startswith("p2_"):
            # Родител 2: ако е зададено едното (име/ЕГН), другото е задължително.
            other = _clean(raw.get("p2_egn" if key == "p2_name" else "p2_name"))
            required = bool(other)
        else:
            required = f["required"]
        if not value:
            if required:
                errors[key] = "Попълнете полето."
            values[key] = ""
            continue
        if len(value) > MAX_VALUE or re.search(r"[\x00-\x1f]", value):
            errors[key] = "Невалидна стойност."
            continue
        if kind == "egn":
            if not re.fullmatch(r"\d{10}", value):
                errors[key] = "ЕГН се състои от 10 цифри."
                continue
        elif kind == "date":
            try:
                value = datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
            except ValueError:
                errors[key] = "Невалидна дата."
                continue
        elif kind == "idno":
            if not re.fullmatch(r"[0-9A-Za-zА-Яа-я/\-]{3,20}", value):
                errors[key] = "Невалиден номер."
                continue
        values[key] = value
    if errors:
        raise FormError(errors)

    return values


# ------------------------------------------------------------------ рендер ---
def _fields():
    global _FIELDS
    if _FIELDS is None:
        with open(os.path.join(TEMPLATE_DIR, "fields.json"), encoding="utf-8") as fh:
            _FIELDS = json.load(fh)
    return _FIELDS


def _ensure_font():
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))


def _fit(text, width):
    """Размер на шрифта, при който текстът се събира в ширината; None, ако не се събира."""
    size = BASE_SIZE
    while size >= MIN_SIZE:
        if pdfmetrics.stringWidth(text, FONT_NAME, size) <= width:
            return size
        size -= 0.5
    return None


def _render_page(template, values):
    """Една страница: шаблонът с наложен текст. Връща pypdf страница."""
    _ensure_font()
    spec = _fields()[template]
    width, height = spec["size"]
    reader = PdfReader(os.path.join(TEMPLATE_DIR, template + ".pdf"))
    page = reader.pages[0]

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    errors = {}
    for key, box in spec["fields"].items():
        text = values.get(key, "")
        if not text:
            continue
        if "cover" in box:
            x0, top0, x1, top1 = box["cover"]
            pdf.setFillColorRGB(1, 1, 1)
            pdf.rect(x0, height - top1, x1 - x0, top1 - top0, stroke=0, fill=1)
        size = _fit(text, box["w"])
        if size is None:
            errors[key] = "Текстът е твърде дълъг за реда в бланката."
            continue
        pdf.setFillColorRGB(0.05, 0.05, 0.35)
        pdf.setFont(FONT_NAME, size)
        pdf.drawString(box["x"], height - box["base"], text)
    pdf.save()
    if errors:
        raise FormError(errors)
    buffer.seek(0)
    page.merge_page(PdfReader(buffer).pages[0])
    return page


def get_club_name():
    row = db.session.get(Setting, CLUB_KEY)
    return (row.value if row is not None and row.value.strip() else DEFAULT_CLUB_NAME)


def build_pdf(category, values, season_end, club_name, child_name):
    """Един PDF: заявление + декларация + медицинско (с името на детето и „Футбол“)."""
    base = dict(values)
    base["club"] = club_name
    base["season"] = f"{season_end - 1}/{season_end}"
    if category == CAT_UNDER14:
        pass
    else:
        base["player_bg2"] = base.get("player_bg", "")  # същото име и във втория ред на заявлението
    writer = PdfWriter()
    for name in (f"application_{category}", f"declaration_{category}"):
        writer.add_page(_render_page(name, base))
    writer.add_page(_render_page("medical", {"name": _clean(child_name), "sport": "Футбол"}))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
