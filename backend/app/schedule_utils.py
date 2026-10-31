"""Тренировъчен график: етикети на слотове и подготовка на публичния изглед."""
from sqlalchemy.orm import selectinload

from app import db
from app.models import KIND_MEN, TEAM_ACTIVE, TrainingGroup, TrainingSlot

DAY_NAMES = ["Понеделник", "Вторник", "Сряда", "Четвъртък", "Петък", "Събота", "Неделя"]


def day_name(number):
    return DAY_NAMES[number - 1]


def _format_run(start, end):
    if start == end:
        return str(start)
    if end == start + 1:
        return f"{start}/{str(end)[2:]}"  # 2018/19
    return f"{start}–{end}"


def slot_label(teams, groups=()):
    """Етикет на слот от свързаните отбори и групи: набор(и) като на графика.

    2018 + 2019 -> „2018/19“; 2014/15 -> „2014/15“; 2016 + 2020 -> „2016, 2020“.
    """
    years = set()
    has_men = False
    for team in teams:
        if team.kind == KIND_MEN:
            has_men = True
            continue
        if team.birth_year_from is not None:
            years.add(team.birth_year_from)
            if team.birth_year_to:
                years.add(team.birth_year_to)

    parts, run = [], []
    for year in sorted(years):
        if run and year == run[-1] + 1:
            run.append(year)
        else:
            if run:
                parts.append(_format_run(run[0], run[-1]))
            run = [year]
    if run:
        parts.append(_format_run(run[0], run[-1]))
    if has_men:
        parts.append("MEN")
    parts.extend(g.name for g in sorted(groups, key=lambda g: g.name.casefold()))
    return ", ".join(parts)


def build_public_schedule(highlight_slug=None):
    """Публичният график, готов за показване (таблица + списък по дни).

    Слот се показва, ако поне един от отборите му е активен, или ако е
    свободен текст без отбори (вратари). highlight_slug маркира слотовете на
    един отбор (`mine`)."""
    slots = (
        TrainingSlot.query.options(selectinload(TrainingSlot.teams), selectinload(TrainingSlot.groups))
        .order_by(TrainingSlot.weekday, TrainingSlot.start_time, TrainingSlot.id)
        .all()
    )

    visible = []
    for slot in slots:
        active = [t for t in slot.teams if t.status == TEAM_ACTIVE]
        groups = list(slot.groups)
        if active or groups:
            label = slot_label(active, groups)
            mine = highlight_slug is not None and any(t.slug == highlight_slug for t in active)
            other = not active  # само групи без отбор (вратари) — пунктирана рамка
        elif not slot.teams and slot.label:
            label, mine, other = slot.label, False, True  # стар слот със свободен текст (преди групите)
        else:
            continue  # всички отбори са архивирани и няма групи -> скрит
        visible.append({
            "day": slot.weekday,
            "time": slot.start_time,
            "label": label,
            "mine": mine,
            "other": other,
        })

    times = sorted({v["time"] for v in visible})
    rows = [
        {"time": t, "cells": [[v for v in visible if v["time"] == t and v["day"] == d] for d in range(1, 8)]}
        for t in times
    ]
    days = [
        {"number": d, "name": day_name(d), "slots": [v for v in visible if v["day"] == d]}
        for d in range(1, 8)
    ]
    mine = [v for v in visible if v["mine"]]
    return {
        "has_slots": bool(visible),
        "day_names": DAY_NAMES,
        "rows": rows,
        "days": days,
        "mine": mine,
        "mine_text": " · ".join(f"{day_name(v['day'])} {v['time']}" for v in mine),
    }


def find_group_by_name(name, ignore_id=None):
    """Група по име, без значение на главни/малки букви. Сравнява се в Python, защото
    lower() на SQLite не разбира кирилица."""
    wanted = name.strip().casefold()
    for group in TrainingGroup.query.all():
        if group.id != ignore_id and group.name.casefold() == wanted:
            return group
    return None


def migrate_label_slots_to_groups():
    """Еднократно (и безопасно при повторно пускане): стари слотове със свободен текст
    (напр. „Вратари — големи“) стават истински групи, които се избират от списък."""
    slots = TrainingSlot.query.filter(TrainingSlot.label != "").all()
    changed = 0
    for slot in slots:
        if slot.teams:
            continue
        name = slot.label.strip()
        group = find_group_by_name(name)
        if group is None:
            group = TrainingGroup(name=name[:40])
            db.session.add(group)
            db.session.flush()
        if group not in slot.groups:
            slot.groups.append(group)
        slot.label = ""
        changed += 1
    if changed:
        db.session.commit()
    return changed
