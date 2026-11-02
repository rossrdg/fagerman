"""Четене на програмата по кръгове от Excel (по един лист на отбор: U8, U9 ... MEN).

Файлът се чете само от командата `flask --app run import-matches` (виж cli.py). Тук няма
запис в базата — функциите връщат редове с предупреждения и грешки, за да се покажат
в прегледа преди записа.

Очаквани колони (първият ред е заглавен; редът на колоните не е важен):
    Кръг | Дата | Час | Домакин | Гост | [Резултат]
Резултатът е в ред „домакин:гост“, напр. 1:4.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional

from app.match_utils import MONTHS_BG
from app.models import (
    KIND_MEN, KIND_YOUTH, MATCH_NOT_PLAYED, MATCH_PLAYED, MATCH_REST, MATCH_SCHEDULED,
    TEAM_ACTIVE, Team,
)
from app.team_utils import u_label

_MONTHS = {name: i for i, name in enumerate(MONTHS_BG) if name}
_DATE_RE = re.compile(r"^(\d{1,2})(?:\s*[–—-]\s*(\d{1,2}))?\s+([а-я]+)\s+(\d{4})$")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")
_SCORE_RE = re.compile(r"^(\d{1,2})\s*[:\-–]\s*(\d{1,2})$")
OUR_KEY = "фагерман"


def clean(value):
    """Текст без невидими интервали, двойни интервали и излишни празни места."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def clean_opponent(value):
    """Като clean(), но маха единична кавичка без чифт (напр. ФК "ПОБЕДА 1945)."""
    text = clean(value)
    if text.count('"') % 2 == 1:
        text = clean(text.replace('"', ""))
    return text


def _is_us(text):
    return clean(text).casefold().replace(" ", "") == OUR_KEY


@dataclass
class ImportRow:
    source_row: int
    round_no: Optional[int] = None
    match_date: Optional[date] = None
    match_time: Optional[time] = None
    is_home: bool = True
    opponent: str = ""
    status: str = MATCH_SCHEDULED
    goals_for: Optional[int] = None
    goals_against: Optional[int] = None
    note: str = ""
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def parse_date(value):
    """(дата, текст на периода или None). Период като „3–4 октомври 2026“ -> първият ден."""
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    text = clean(value).casefold()
    found = _DATE_RE.match(text)
    if not found:
        raise ValueError(f"не разбирам датата „{clean(value)}“")
    day, day_to, month_name, year = found.groups()
    month = _MONTHS.get(month_name)
    if month is None:
        raise ValueError(f"непознат месец „{month_name}“")
    try:
        parsed = date(int(year), month, int(day))
    except ValueError:
        raise ValueError(f"невалидна дата „{clean(value)}“") from None
    return parsed, (clean(value) if day_to else None)


def parse_time(value):
    """(час или None, текст, ако клетката съдържа нещо друго — напр. „(Непроведена)“)."""
    if value is None or clean(value) == "":
        return None, ""
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0), ""
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0), ""
    text = clean(value)
    found = _TIME_RE.match(text)
    if found:
        return time(int(found.group(1)), int(found.group(2))), ""
    return None, text


def parse_sheet(ws):
    """Връща списък ImportRow за един лист."""
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if header is None:
        return []
    columns = {}
    for index, name in enumerate(header):
        key = clean(name).casefold()
        if key:
            columns[key] = index
    missing = [n for n in ("кръг", "дата", "час", "домакин", "гост") if n not in columns]
    if missing:
        raise ValueError("липсват колони: " + ", ".join(missing))

    def cell(row, name):
        index = columns.get(name)
        return row[index] if index is not None and index < len(row) else None

    result = []
    seen_rounds = set()
    last_round = 0
    last_date = None
    for number, row in enumerate(rows_iter, start=2):
        if not any(clean(v) for v in row):
            continue
        item = ImportRow(source_row=number)
        result.append(item)

        # --- кръг ---
        found = re.search(r"\d+", clean(cell(row, "кръг")))
        if not found:
            item.errors.append("няма номер на кръга")
            continue
        item.round_no = int(found.group())
        if item.round_no in seen_rounds:
            item.warnings.append(f"кръг {item.round_no} се повтаря — зареден като кръг {last_round + 1}")
            item.round_no = last_round + 1
        seen_rounds.add(item.round_no)
        last_round = max(last_round, item.round_no)

        # --- дата ---
        try:
            item.match_date, range_text = parse_date(cell(row, "дата"))
        except ValueError as err:
            item.errors.append(str(err))
            continue
        if range_text:
            item.note = range_text
        if last_date and item.match_date < last_date:
            item.warnings.append(f"датата {item.match_date:%d.%m.%Y} е преди тази на предишния кръг — проверете я")
        last_date = max(last_date, item.match_date) if last_date else item.match_date

        home_raw, away_raw = clean(cell(row, "домакин")), clean(cell(row, "гост"))
        home_text, away_text = clean_opponent(home_raw), clean_opponent(away_raw)
        for raw, fixed in ((home_raw, home_text), (away_raw, away_text)):
            if raw != fixed:
                item.warnings.append(f"махната единична кавичка: „{raw}“ -> „{fixed}“")

        # --- почивен кръг ---
        if "почива" in home_text.casefold() or "почива" in away_text.casefold():
            item.status = MATCH_REST
            continue

        # --- домакин / гост ---
        if _is_us(home_text) and not _is_us(away_text):
            item.is_home, item.opponent = True, away_text
        elif _is_us(away_text) and not _is_us(home_text):
            item.is_home, item.opponent = False, home_text
        else:
            item.errors.append(f"не намирам „ФА Герман“ като домакин или гост ({home_text} – {away_text})")
            continue
        if not item.opponent:
            item.errors.append("липсва съперник")
            continue

        # --- час (или бележка вместо час) ---
        item.match_time, time_text = parse_time(cell(row, "час"))
        if time_text:
            if "непровед" in time_text.casefold():
                item.status = MATCH_NOT_PLAYED
            else:
                item.errors.append(f"не разбирам часа „{time_text}“")
                continue

        # --- резултат (по избор): домакин:гост ---
        score_text = clean(cell(row, "резултат"))
        if score_text:
            found = _SCORE_RE.match(score_text)
            if not found:
                item.errors.append(f"не разбирам резултата „{score_text}“")
                continue
            first, second = int(found.group(1)), int(found.group(2))
            item.goals_for, item.goals_against = (first, second) if item.is_home else (second, first)
            if item.status == MATCH_NOT_PLAYED:
                item.errors.append("мачът е „непроведен“, но има резултат")
                continue
            item.status = MATCH_PLAYED
    return result


def resolve_team(sheet_title, season_end):
    """Листът „U8“ е отборът, който през този сезон носи етикет U8; „MEN“ е мъжкият отбор."""
    title = clean(sheet_title).upper()
    if title == "MEN":
        return Team.query.filter_by(kind=KIND_MEN, status=TEAM_ACTIVE).first()
    for team in Team.query.filter_by(kind=KIND_YOUTH, status=TEAM_ACTIVE).all():
        if u_label(team, season_end).upper() == title:
            return team
    return None
