"""Магазин: проверка на данните за артикул, цени в евро/евроцента, снимки.

Цените идват от админа като число или текст („41“, „41,50“, „41.5 €“) и се пазят
в евроцентове. Проверката се ползва и от админ API, и от внасянето от Excel.
"""
import os
import re
import uuid
from decimal import Decimal, InvalidOperation

from flask import current_app

from app.models import (
    ADULT_SIZES, CHILD_SIZES, DEFAULT_PERSONALIZATION_FEE_CENTS, ONE_SIZE_LABEL, SIZE_ADULT, SIZE_BOTH, SIZE_CHILD,
    SIZE_MODES, SIZE_ONE, Product, sizes_for, thumb_url,
)

MAX_NAME = 120
MAX_PRICE_CENTS = 999_999  # 9 999,99 €
MAX_FEE_CENTS = 99_999     # 999,99 €
IMAGE_URL = re.compile(r"^/uploads/[0-9a-f]{20}\.jpg$")


def parse_cents(value, allow_zero=True):
    """Евро -> евроцентове. None при празно; ValueError при невалидна стойност."""
    if value is None or isinstance(value, bool):
        if value is None:
            return None
        raise ValueError
    if isinstance(value, str):
        value = value.replace("€", "").replace("\u00a0", "").replace(" ", "").replace(",", ".")
        if value == "":
            return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError
    if not amount.is_finite() or amount < 0 or (amount == 0 and not allow_zero):
        raise ValueError
    cents = amount * 100
    if cents != cents.to_integral_value():  # повече от 2 знака след запетаята
        raise ValueError
    return int(cents)


def format_eur(cents):
    """4100 -> „41“, 4150 -> „41,50“ (за показване в админа и в имейлите)."""
    if cents is None:
        return ""
    return f"{cents // 100}" if cents % 100 == 0 else f"{cents // 100},{cents % 100:02d}"


def current_values(product):
    """Стойностите на артикула във вида, в който ги приема validate_product."""
    d = product.to_dict()
    return {
        "name": d["name"], "size_mode": d["size_mode"],
        "price_child": d["price_child"], "price_adult": d["price_adult"],
        "allows_personalization": d["allows_personalization"],
        "personalization_fee": d["personalization_fee"],
        "sold_out_sizes": d["sold_out_sizes"], "image": d["image"], "is_visible": d["is_visible"],
    }


def validate_product(values):
    """Връща (cleaned, errors). errors е речник поле -> съобщение (празен = всичко е наред)."""
    errors, c = {}, {}

    name = values.get("name")
    name = re.sub(r"\s+", " ", name).strip() if isinstance(name, str) else ""
    if not name:
        errors["name"] = "Въведете име на артикула."
    elif len(name) > MAX_NAME:
        errors["name"] = f"Името е твърде дълго (до {MAX_NAME} знака)."
    c["name"] = name

    mode = values.get("size_mode") or SIZE_BOTH
    if mode not in SIZE_MODES:
        errors["size_mode"] = "Изберете вид размери."
        mode = SIZE_BOTH
    c["size_mode"] = mode

    def price(key, label, needed=True):
        try:
            cents = parse_cents(values.get(key), allow_zero=False)
        except ValueError:
            errors[key] = f"{label}: въведете цена в евро, напр. 41 или 41,50."
            return None
        if cents is not None and cents > MAX_PRICE_CENTS:
            errors[key] = f"{label}: цената е твърде висока."
            return None
        if cents is None and needed and key not in errors:
            errors[key] = f"{label}: въведете цена."
        return cents

    child_used = mode in (SIZE_BOTH, SIZE_CHILD)
    adult_used = mode in (SIZE_BOTH, SIZE_ADULT, SIZE_ONE)
    c["price_child_cents"] = price("price_child", "Цена детски", True) if child_used else None
    c["price_adult_cents"] = price("price_adult", "Цена" if mode == SIZE_ONE else "Цена възрастен", True) \
        if adult_used else None

    c["allows_personalization"] = bool(values.get("allows_personalization", False))
    try:
        fee = parse_cents(values.get("personalization_fee"))
    except ValueError:
        errors["personalization_fee"] = "Доплащане: въведете сума в евро, напр. 5 или 7,50."
        fee = DEFAULT_PERSONALIZATION_FEE_CENTS
    if fee is None:
        fee = DEFAULT_PERSONALIZATION_FEE_CENTS
    if fee > MAX_FEE_CENTS:
        errors["personalization_fee"] = "Доплащане: сумата е твърде висока."
    c["personalization_fee_cents"] = fee

    sold = values.get("sold_out_sizes") or []
    if not isinstance(sold, list):
        sold = []
    allowed = sizes_for(mode)
    c["sold_out_sizes"] = ",".join(s for s in allowed if s in sold)  # само размерите на режима, в реда им

    image = values.get("image")
    if image in (None, ""):
        c["image"] = None
    elif isinstance(image, str) and IMAGE_URL.match(image):
        c["image"] = image
    else:
        errors["image"] = "Невалидна снимка. Качете я наново."
    c["is_visible"] = bool(values.get("is_visible", True))
    return c, errors


def apply_cleaned(product, cleaned):
    product.name = cleaned["name"]
    product.size_mode = cleaned["size_mode"]
    product.price_child_cents = cleaned["price_child_cents"]
    product.price_adult_cents = cleaned["price_adult_cents"]
    product.allows_personalization = cleaned["allows_personalization"]
    product.personalization_fee_cents = cleaned["personalization_fee_cents"]
    product.sold_out_sizes = cleaned["sold_out_sizes"]
    product.image = cleaned["image"]
    product.is_visible = cleaned["is_visible"]


def next_sort_order():
    last = Product.query.order_by(Product.sort_order.desc()).first()
    return (last.sort_order + 1) if last else 1


# ---------------------------------------------------------------- снимки ---
def image_name(url):
    """/uploads/<име>.jpg -> <име>; None за всичко друго."""
    return url[len("/uploads/"):-len(".jpg")] if url and IMAGE_URL.match(url) else None


def remove_image_files(url):
    """Трие файловете на снимката, ако не я ползва друг артикул."""
    from app.gallery_utils import remove_files

    name = image_name(url)
    if name and not Product.query.filter_by(image=url).first():
        remove_files([name])


def store_image_file(path):
    """Чете снимка от диска, смалява я като качените през админа (1600 px + 800 px версия)
    и връща адреса й /uploads/<име>.jpg. ValueError, ако файлът не е снимка."""
    from PIL import Image, UnidentifiedImageError

    from app.routes.uploads import MAIN_SIZE, MAX_PIXELS, READABLE_FORMATS, THUMB_SIZE, _save_jpeg, _to_rgb

    try:
        with Image.open(path, formats=READABLE_FORMATS) as img:
            if img.width * img.height > MAX_PIXELS:
                raise ValueError("твърде голяма резолюция")
            img.load()
            rgb = _to_rgb(img)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("не е снимка или форматът не се поддържа")

    folder = current_app.config["UPLOAD_DIR"]
    os.makedirs(folder, exist_ok=True)
    name = uuid.uuid4().hex[:20]
    _save_jpeg(rgb, os.path.join(folder, f"{name}.jpg"), MAIN_SIZE)
    _save_jpeg(rgb, os.path.join(folder, f"{name}-800.jpg"), THUMB_SIZE)
    return f"/uploads/{name}.jpg"


# ----------------------------------------------------- публичен изглед ---
def _price_range_text(cents_list):
    cents_list = [c for c in cents_list if c is not None]
    low, high = min(cents_list), max(cents_list)
    return f"{format_eur(low)} €" if low == high else f"{format_eur(low)} – {format_eur(high)} €"


def public_dict(product):
    """Артикулът така, както го вижда посетителят (за страницата /shop и количката).

    groups = групи размери с обща цена: за „детски и възрастни“ са две, за „един размер“ — една
    група с един размер. Изчерпаните размери са отбелязани, но се показват (зачеркнати).
    """
    sold = set(product.sold_out_list)
    groups = []
    if product.size_mode in (SIZE_BOTH, SIZE_CHILD):
        groups.append(("child", "Детски", CHILD_SIZES, product.price_child_cents))
    if product.size_mode in (SIZE_BOTH, SIZE_ADULT):
        groups.append(("adult", "Възрастни", ADULT_SIZES, product.price_adult_cents))
    if product.size_mode == SIZE_ONE:
        groups.append(("one", "", [ONE_SIZE_LABEL], product.price_adult_cents))
    return {
        "id": product.id,
        "name": product.name,
        "image": product.image,
        "thumb": thumb_url(product.image),
        "price_text": _price_range_text([g[3] for g in groups]),
        "one_size": product.size_mode == SIZE_ONE,
        # Име и номер срещу доплащане (на брой); None, ако артикулът не се персонализира.
        "personalization": ({"fee": product.personalization_fee_cents / 100 if product.personalization_fee_cents % 100
                             else product.personalization_fee_cents // 100}
                            if product.allows_personalization else None),
        "groups": [
            {"key": key, "label": label, "price": cents / 100 if cents % 100 else cents // 100,
             "sizes": [{"size": size, "sold_out": size in sold} for size in sizes]}
            for key, label, sizes, cents in groups
        ],
    }


def public_products():
    """Видимите артикули в реда, зададен от админа."""
    items = Product.query.filter_by(is_visible=True).order_by(Product.sort_order, Product.id).all()
    return [public_dict(p) for p in items]


def price_for_size(product, size):
    """(цена в евроцентове, име на групата, изчерпан?) за размер на артикул; None, ако размерът не съществува."""
    if product.size_mode in (SIZE_BOTH, SIZE_CHILD) and size in CHILD_SIZES:
        return product.price_child_cents, "Детски", size in product.sold_out_list
    if product.size_mode in (SIZE_BOTH, SIZE_ADULT) and size in ADULT_SIZES:
        return product.price_adult_cents, "Възрастни", size in product.sold_out_list
    if product.size_mode == SIZE_ONE and size == ONE_SIZE_LABEL:
        return product.price_adult_cents, "", size in product.sold_out_list
    return None
