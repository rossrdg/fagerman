"""Логика за отборите: сезон, U етикет, набор, подредба.

Правилото за U етикета: U = крайна година на сезона − най-старата година на
набора. За сезон 2026/27 (крайна година 2027): набор 2020 -> U7, 2016 -> U11,
2014/15 -> U13, 2012/13 -> U15.
"""
from datetime import date

from sqlalchemy.exc import IntegrityError

from app import db
from app.models import KIND_MEN, Setting

SEASON_KEY = "season_end_year"


def get_season_end_year():
    """Текущият сезон (крайната му година, напр. 2027 за 2026/27).

    Първият път се пази в базата и после НЕ се сменя сам с времето — сменя
    се само ръчно от главния администратор (бутон „Нов сезон“, по-късна стъпка).
    """
    row = db.session.get(Setting, SEASON_KEY)
    if row is not None:
        try:
            return int(row.value)
        except ValueError:
            pass

    today = date.today()
    year = today.year + 1 if today.month >= 7 else today.year  # сезонът започва през лятото
    try:
        if row is None:
            db.session.add(Setting(key=SEASON_KEY, value=str(year)))
        else:
            row.value = str(year)
        db.session.commit()
    except IntegrityError:  # две заявки едновременно — другата вече го е записала
        db.session.rollback()
        row = db.session.get(Setting, SEASON_KEY)
        return int(row.value)
    return year


def season_text(season_end_year):
    return f"{season_end_year - 1}/{str(season_end_year)[2:]}"


def cohort_slug(birth_from, birth_to):
    return str(birth_from) if not birth_to else f"{birth_from}-{birth_to}"


def cohort_text(team):
    """„2020“ или „2014/15“. Празно за мъжкия отбор."""
    if team.kind == KIND_MEN or team.birth_year_from is None:
        return ""
    if not team.birth_year_to:
        return str(team.birth_year_from)
    return f"{team.birth_year_from}/{str(team.birth_year_to)[2:]}"


def cohort_label(team):
    """„набор 2020“ / „набори 2014/15“ / „мъжки отбор“."""
    if team.kind == KIND_MEN:
        return "мъжки отбор"
    return ("набори " if team.birth_year_to else "набор ") + cohort_text(team)


def auto_label(team, season_end_year):
    if team.kind == KIND_MEN:
        return "MEN"
    return f"U{season_end_year - team.birth_year_from}"


def u_label(team, season_end_year):
    return team.u_override or auto_label(team, season_end_year)


def sort_key(team):
    """Най-малките първи (U6, U7, ...), мъжкият отбор накрая."""
    if team.kind == KIND_MEN or team.birth_year_from is None:
        return (1, 0)
    return (0, -team.birth_year_from)
