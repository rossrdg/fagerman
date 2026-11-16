"""Известия: кой ги вижда, състояние (насрочено / активно / изтекло / скрито), получатели."""
from app.match_utils import MONTHS_BG, today_sofia
from app.models import AUD_ALL, AUD_PLAYER, AUD_TEAM, Announcement, ParentAccount, Player
from app.player_utils import player_team


def today():
    return today_sofia()


def state(a, day=None):
    day = day or today()
    if a.is_hidden:
        return "hidden"
    if a.publish_date > day:
        return "scheduled"
    if a.expires_date is not None and a.expires_date < day:
        return "expired"
    return "active"


STATE_LABELS = {"active": "Показва се", "scheduled": "Насрочено", "expired": "Изтекло", "hidden": "Скрито"}


def date_text(day):
    return f"{day.day} {MONTHS_BG[day.month]} {day.year}"


def children_for(announcement, children):
    """Децата (от списъка `children` на един родител), за които важи известието."""
    if announcement.audience == AUD_ALL:
        return list(children)
    if announcement.audience == AUD_PLAYER:
        return [c for c in children if c.id == announcement.player_id]
    result = []
    for child in children:
        team = player_team(child)[0]
        if team is not None and team.id == announcement.team_id:
            result.append(child)
    return result


def recipients(announcement):
    """Колко родители (акаунта с активно дете) получават известието."""
    parents = set()
    for player in Player.query.filter_by(archived=False).all():
        if children_for(announcement, [player]):
            parents.add(player.parent_id)
    return len(parents)


def audience_text(announcement):
    if announcement.audience == AUD_ALL:
        return "Всички родители"
    if announcement.audience == AUD_TEAM:
        from app.team_utils import get_season_end_year, u_label
        team = announcement.team
        return f"Отбор {u_label(team, get_season_end_year())}" if team is not None else "Отбор (изтрит)"
    return f"Дете: {announcement.player.child_name}" if announcement.player is not None else "Дете"


def visible_for_parent(parent):
    """Известията, които родителят трябва да види днес: [(известие, [деца])], най-новите първи."""
    day = today()
    children = Player.query.filter_by(parent_id=parent.id, archived=False).order_by(Player.child_name).all()
    out = []
    for a in Announcement.query.order_by(Announcement.publish_date.desc(), Announcement.id.desc()).all():
        if state(a, day) != "active":
            continue
        who = children_for(a, children)
        if who:
            out.append((a, who))
    return out
