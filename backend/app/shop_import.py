"""Внасяне на артикулите на магазина от Excel (еднократно, а при нужда и повторно).

Колони (по заглавията, редът няма значение): Име · Цена детски · Цена възрастен · Размери
(един размер / и двете / детски / възрастни) · Персонализация (да/не) · Доплащане · Файл със снимка.
Снимките се намират по името на файла, без значение главни/малки букви, интервали, „€“,
долни черти и разширение (.png / .PNG).
"""
import os
import re
from dataclasses import dataclass, field

from app.models import (
    DEFAULT_PERSONALIZATION_FEE_CENTS, SIZE_ADULT, SIZE_BOTH, SIZE_CHILD, SIZE_ONE,
)
from app.shop_utils import parse_cents, validate_product

COLUMNS = {
    "name": ("име",),
    "price_child": ("цена детски",),
    "price_adult": ("цена възрастен",),
    "sizes": ("размери",),
    "personalization": ("персонализация",),
    "fee": ("доплащане",),
    "image": ("файл със снимка", "снимка"),
}
SIZE_WORDS = {
    "един размер": SIZE_ONE, "един": SIZE_ONE,
    "и двете": SIZE_BOTH, "двете": SIZE_BOTH, "детски и възрастни": SIZE_BOTH,
    "детски": SIZE_CHILD, "възрастни": SIZE_ADULT, "възрастен": SIZE_ADULT,
}
YES = {"да", "yes", "y", "1", "true"}
NO = {"не", "no", "n", "0", "false", ""}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff", ".avif"}


@dataclass
class ImportRow:
    source_row: int
    name: str = ""
    cleaned: dict = None
    image_file: str = ""
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def norm(text):
    """Име на файл -> ключ за сравнение: без разширение, само букви и цифри, малки букви."""
    base = os.path.splitext(str(text).strip())[0] if os.path.splitext(str(text).strip())[1].lower() in IMAGE_EXTENSIONS \
        else str(text).strip()
    return re.sub(r"[\W_]+", "", base.casefold())


def index_images(folder):
    """{ключ: [пътища]} за всички снимки в папката (без подпапки)."""
    found = {}
    for entry in sorted(os.listdir(folder)):
        path = os.path.join(folder, entry)
        if os.path.isfile(path) and os.path.splitext(entry)[1].lower() in IMAGE_EXTENSIONS:
            found.setdefault(norm(entry), []).append(path)
    return found


def _cell(value):
    return "" if value is None else str(value).strip()


def find_columns(header_row):
    columns = {}
    for index, title in enumerate(header_row):
        text = _cell(title).casefold()
        for key, starts in COLUMNS.items():
            if key not in columns and any(text.startswith(s) for s in starts):
                columns[key] = index
    missing = [COLUMNS[k][0] for k in ("name", "sizes") if k not in columns]
    if missing:
        raise ValueError("липсват колони: " + ", ".join(missing))
    return columns


def parse_sheet(ws):
    """Връща списък от ImportRow. ValueError, ако заглавията не се разпознават."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("празен лист")
    columns = find_columns(rows[0])

    def get(row, key):
        index = columns.get(key)
        return row[index] if index is not None and index < len(row) else None

    result = []
    for number, row in enumerate(rows[1:], start=2):
        if not any(_cell(v) for v in row):
            continue
        item = ImportRow(source_row=number, name=_cell(get(row, "name")), image_file=_cell(get(row, "image")))

        word = _cell(get(row, "sizes")).casefold()
        mode = SIZE_WORDS.get(word)
        if mode is None:
            item.errors.append(f"непознат размер „{_cell(get(row, 'sizes'))}“ (очаквам: един размер, и двете, детски, възрастни)")
            mode = SIZE_BOTH

        pers = _cell(get(row, "personalization")).casefold()
        if pers not in YES | NO:
            item.errors.append(f"персонализацията трябва да е „да“ или „не“, а не „{pers}“")

        child, adult = get(row, "price_child"), get(row, "price_adult")
        if mode == SIZE_ONE:
            # Единствената цена е в price_adult; ако са попълнени и двете, трябва да са равни.
            try:
                c, a = parse_cents(child), parse_cents(adult)
            except ValueError:
                c = a = None
            if c is not None and a is not None and c != a:
                item.errors.append("при „един размер“ цената трябва да е една (детската и възрастната се различават)")
            if adult in (None, "") and child not in (None, ""):
                adult = child
            child = None
        elif mode == SIZE_ADULT:
            if child not in (None, ""):
                item.warnings.append("артикулът е само за възрастни — детската цена се игнорира")
            child = None
        elif mode == SIZE_CHILD:
            if adult not in (None, ""):
                item.warnings.append("артикулът е само за деца — цената за възрастни се игнорира")
            adult = None

        fee = get(row, "fee")
        values = {
            "name": item.name, "size_mode": mode, "price_child": child, "price_adult": adult,
            "allows_personalization": pers in YES,
            "personalization_fee": fee if _cell(fee) else DEFAULT_PERSONALIZATION_FEE_CENTS / 100,
            "sold_out_sizes": [], "image": None, "is_visible": True,
        }
        cleaned, errors = validate_product(values)
        item.errors.extend(errors.values())
        item.cleaned = cleaned
        if pers in YES and not _cell(fee):
            item.warnings.append(f"доплащане за персонализация не е зададено — взима се {DEFAULT_PERSONALIZATION_FEE_CENTS // 100} € по подразбиране")
        result.append(item)
    return result
