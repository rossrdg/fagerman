"""Документи за картотекиране: видове, комплект по възраст, бланки на БФС, текст на инструкциите.

Категорията се определя от U числото за сезона (сезон − година на раждане):
до U13 -> „до 14 г.“, U14–U17 -> „14–18 г.“, U18 и нагоре -> „18+“."""
import os

from app import db
from app.models import (
    DOC_APPROVED, DOC_RETURNED, DOC_UPLOADED, DOC_WAITING, CardSeason, PlayerDocument,
)

DOC_APPLICATION = "application"
DOC_DECLARATION = "declaration"
DOC_BIRTH_CERT = "birth_certificate"
DOC_ID_CARD = "id_card"
DOC_PHOTO = "photo"
DOC_MEDICAL = "medical"

CAT_UNDER14 = "under14"
CAT_MINOR = "minor"
CAT_ADULT = "adult"
CATEGORY_LABELS = {CAT_UNDER14: "до 14 г.", CAT_MINOR: "14–18 г.", CAT_ADULT: "18+"}

DOC_TYPES = {
    DOC_APPLICATION: {
        "title": "Заявление за картотекиране",
        "hint": "Попълнено и подписано от родител (за 14–18 г. — и от състезателя; за 18+ — от състезателя).",
    },
    DOC_DECLARATION: {
        "title": "Декларация",
        "hint": "Попълнена и подписана. Достатъчен е подпис от един родител, където бланката го позволява.",
    },
    DOC_BIRTH_CERT: {
        "title": "Акт за раждане (копие)",
        "hint": "Ясна снимка или скан на акта за раждане.",
    },
    DOC_ID_CARD: {
        "title": "Лична карта (двете страни)",
        "hint": "Ясна снимка на двете страни на личната карта. Може да качите до два файла.",
    },
    DOC_PHOTO: {
        "title": "Актуална снимка",
        "hint": "Скорошна снимка на детето, анфас. Използва се само за картотеката.",
    },
    DOC_MEDICAL: {
        "title": "Медицинско удостоверение (Приложение № 4)",
        "hint": "Попълва се и се подписва от лекар. Снимка или скан на целия документ.",
    },
}

# Подсказки по категория (за заявлението и декларацията — различни са кой ги подписва).
_HINTS = {
    (DOC_APPLICATION, CAT_UNDER14): "Попълнено и подписано от родителите. Достатъчен е подпис от един родител.",
    (DOC_APPLICATION, CAT_MINOR): "Попълнено и подписано от състезателя, със съгласието на родителите (подпис на родител).",
    (DOC_APPLICATION, CAT_ADULT): "Попълнено и подписано от състезателя.",
    (DOC_DECLARATION, CAT_UNDER14): "Попълнена и подписана от родителите. Достатъчен е подпис от един родител.",
    (DOC_DECLARATION, CAT_MINOR): "Попълнена и подписана от състезателя и от родител.",
    (DOC_DECLARATION, CAT_ADULT): "Попълнена и подписана от състезателя.",
}


def hint_for(doc_type, category):
    return _HINTS.get((doc_type, category)) or DOC_TYPES.get(doc_type, {}).get("hint", "")


# Бланки на БФС (оригинални; текстът им не се променя). Ключ: (вид, категория); None = за всички категории.
_TEMPLATES = {
    (DOC_APPLICATION, CAT_UNDER14): "application_under14.pdf",
    (DOC_APPLICATION, CAT_MINOR): "application_minor.pdf",
    (DOC_APPLICATION, CAT_ADULT): "application_adult.pdf",
    (DOC_DECLARATION, CAT_UNDER14): "declaration_under14.pdf",
    (DOC_DECLARATION, CAT_MINOR): "declaration_minor.pdf",
    (DOC_DECLARATION, CAT_ADULT): "declaration_adult.pdf",
    (DOC_MEDICAL, None): "medical.pdf",
}
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bfs_templates")

# ЧЕРНОВА: окончателният текст се пише от академията.
INSTRUCTIONS = [
    "Изтеглете бланките за детето от списъка по-долу (заявление, декларация и медицинско удостоверение).",
    "Разпечатайте ги, попълнете ги и ги подпишете. Медицинското удостоверение се попълва от лекар.",
    "Снимайте или сканирайте всеки документ така, че да се чете ясно, и го качете на съответния ред. Нужни са още копие от акта за раждане или от личната карта и актуална снимка на детето.",
    "Когато документът е качен, натиснете „Изпрати за проверка“.",
    "Треньорът ще ги прегледа. Ако нещо трябва да се поправи, ще го видите като коментар на реда на документа.",
    "Няма срок, който тече — колкото по-скоро завършите картотекирането, толкова по-добре за детето.",
]


def category_for(player, season_end):
    number = season_end - player.birth_date.year
    if number <= 13:
        return CAT_UNDER14
    return CAT_MINOR if number <= 17 else CAT_ADULT


def default_doc_types(category):
    third = DOC_BIRTH_CERT if category == CAT_UNDER14 else DOC_ID_CARD
    return [DOC_APPLICATION, DOC_DECLARATION, third, DOC_PHOTO, DOC_MEDICAL]


def template_path(doc_type, category):
    name = _TEMPLATES.get((doc_type, category)) or _TEMPLATES.get((doc_type, None))
    if not name:
        return None
    path = os.path.join(TEMPLATE_DIR, name)
    return path if os.path.exists(path) else None


def ensure_set(player, season_end):
    """Комплектът на детето за сезона: създава се при първо отваряне (с документите по възраст).
    Връща (CardSeason, списък документи). Извикващият прави commit."""
    card = CardSeason.query.filter_by(player_id=player.id, season_end=season_end).first()
    if card is None:
        card = CardSeason(player_id=player.id, season_end=season_end)
        db.session.add(card)
        for doc_type in default_doc_types(category_for(player, season_end)):
            db.session.add(PlayerDocument(player_id=player.id, season_end=season_end, doc_type=doc_type))
        db.session.flush()
        db.session.refresh(player)
    docs = [d for d in player.documents if d.season_end == season_end]
    order = list(DOC_TYPES)
    docs.sort(key=lambda d: order.index(d.doc_type) if d.doc_type in order else 99)
    return card, docs


def summary(card, docs):
    """{done, total, pending, returned, card_received} за списъка „Футболисти“."""
    return {
        "done": sum(1 for d in docs if d.status == DOC_APPROVED),
        "total": len(docs),
        "pending": sum(1 for d in docs if d.status == DOC_UPLOADED),
        "returned": sum(1 for d in docs if d.status == DOC_RETURNED),
        "waiting": sum(1 for d in docs if d.status == DOC_WAITING),
        "card_received": card.card_received_at is not None,
    }


def purge_files(docs):
    """Изтрива файловете на документите (редове в базата + шифровани файлове); документите
    остават без файлове. Връща имената, които извикващият трие след commit."""
    names = []
    for doc in docs:
        for file in list(doc.files):
            names.append(file.name)
            db.session.delete(file)
    return names
