"""Помощни функции за мачовете: български дати, показване на резултата, речници за API."""
from datetime import date, datetime, timedelta

from app.models import (
    MATCH_NOT_PLAYED, MATCH_PLAYED, MATCH_POSTPONED, MATCH_REST, MATCH_SCHEDULED,
    TEAM_ACTIVE, Match, Team,
)
from app.team_utils import season_text, sort_key, u_label

OUR_NAME = "ФА Герман"

STATUS_LABELS = {
    MATCH_SCHEDULED: "Насрочен",
    MATCH_PLAYED: "Изигран",
    MATCH_POSTPONED: "Отложен",
    MATCH_NOT_PLAYED: "Непроведен",
    MATCH_REST: "Почива",
}

WEEKDAYS_BG = ["понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя"]
MONTHS_BG = ["", "януари", "февруари", "март", "април", "май", "юни",
             "юли", "август", "септември", "октомври", "ноември", "декември"]


def date_text(day):
    """„събота, 14 ноември“ (годината не се показва — афишът е за текущия сезон)."""
    if day is None:
        return ""
    return f"{WEEKDAYS_BG[day.weekday()]}, {day.day} {MONTHS_BG[day.month]}"


def date_short(day):
    return day.strftime("%d.%m.%Y") if day else ""


def home_away_names(match):
    """(домакин, гост) така, както се показват на сайта."""
    if match.is_home:
        return OUR_NAME, match.opponent
    return match.opponent, OUR_NAME


def score_text(match):
    """Резултатът в ред „домакин:гост“, напр. „3:1“. None, ако няма резултат."""
    if match.goals_for is None or match.goals_against is None:
        return None
    home, away = ((match.goals_for, match.goals_against) if match.is_home
                  else (match.goals_against, match.goals_for))
    return f"{home}:{away}"


def outcome(match):
    """„win“ / „draw“ / „loss“ от гледна точка на академията, или None."""
    if match.goals_for is None or match.goals_against is None:
        return None
    if match.goals_for > match.goals_against:
        return "win"
    return "draw" if match.goals_for == match.goals_against else "loss"


def match_dict(match, season_end_now=None):
    home, away = home_away_names(match)
    team = match.team
    return {
        "id": match.id,
        "team_id": match.team_id,
        "team_slug": team.slug if team else None,
        "team_label": u_label(team, match.season_end) if team else "",
        "season_end": match.season_end,
        "season_text": season_text(match.season_end),
        "round_no": match.round_no,
        "date": match.match_date.isoformat() if match.match_date else None,
        "date_text": date_text(match.match_date),
        "date_short": date_short(match.match_date),
        "time": match.match_time.strftime("%H:%M") if match.match_time else None,
        "is_home": bool(match.is_home),
        "home": home if match.status != MATCH_REST else "",
        "away": away if match.status != MATCH_REST else "",
        "opponent": match.opponent,
        "venue": match.venue or "",
        "status": match.status,
        "status_label": STATUS_LABELS.get(match.status, match.status),
        "goals_for": match.goals_for,
        "goals_against": match.goals_against,
        "score": score_text(match),
        "outcome": outcome(match),
        "note": match.note or "",
        "created_by": match.created_by or "",
        "updated_by": match.updated_by or "",
        "updated_at": match.updated_at.isoformat() if match.updated_at else None,
    }


def sort_matches(matches):
    """По кръг (без кръг — накрая), после по дата и час."""
    def key(m):
        return (
            m.round_no is None, m.round_no or 0,
            m.match_date is None, m.match_date.toordinal() if m.match_date else 0,
            m.match_time.isoformat() if m.match_time else "99",
            m.id or 0,
        )
    return sorted(matches, key=key)


# ------------------------------------------------------- публични страници ---
def today_sofia():
    """Днешната дата по софийско време (хостингът може да е в друга часова зона)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Sofia")).date()
    except Exception:  # няма tz база данни (напр. Windows без пакета tzdata)
        return date.today()


def monday_of(day):
    return day - timedelta(days=day.weekday())


def public_dict(match):
    """Като match_dict, но без вътрешните полета (кой и кога е въвел мача)."""
    data = match_dict(match)
    for key in ("created_by", "updated_by", "updated_at", "team_id"):
        data.pop(key, None)
    return data


def week_range_text(monday):
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month and monday.year == sunday.year:
        return f"{monday.day} – {sunday.day} {MONTHS_BG[sunday.month]} {sunday.year}"
    if monday.year == sunday.year:
        return f"{monday.day} {MONTHS_BG[monday.month]} – {sunday.day} {MONTHS_BG[sunday.month]} {sunday.year}"
    return (f"{monday.day} {MONTHS_BG[monday.month]} {monday.year} – "
            f"{sunday.day} {MONTHS_BG[sunday.month]} {sunday.year}")


def _poster_matches(season_end):
    """Мачовете за афиша: с дата, не почивни, само от активни отбори."""
    return (Match.query.join(Team, Match.team_id == Team.id)
            .filter(Match.season_end == season_end, Team.status == TEAM_ACTIVE,
                    Match.match_date.isnot(None), Match.status != MATCH_REST).all())


def build_week(season_end, week_param=None, today=None):
    """Данни за седмичния афиш /matches.

    Без избрана седмица се показва най-близката седмица с мачове: текущата, ако има мачове в нея,
    иначе най-близката предстояща, а ако няма такава — последната изиграна. Стрелките
    прескачат седмиците без мачове (почивни периоди).
    """
    today = today or today_sofia()
    matches = _poster_matches(season_end)
    weeks = sorted({monday_of(m.match_date) for m in matches})
    this_monday = monday_of(today)

    chosen = None
    if week_param:
        try:
            chosen = monday_of(date.fromisoformat(week_param))
        except ValueError:
            chosen = None
    if chosen is None:
        if this_monday in weeks:
            chosen = this_monday
        else:
            upcoming = [w for w in weeks if w > this_monday]
            past = [w for w in weeks if w < this_monday]
            chosen = upcoming[0] if upcoming else (past[-1] if past else this_monday)

    earlier = [w for w in weeks if w < chosen]
    later = [w for w in weeks if w > chosen]

    team_order = {}
    in_week = [m for m in matches if monday_of(m.match_date) == chosen]
    for m in in_week:
        team_order.setdefault(m.team_id, sort_key(m.team))
    in_week.sort(key=lambda m: (m.match_date, m.match_time is None,
                                m.match_time.isoformat() if m.match_time else "",
                                team_order[m.team_id], m.round_no or 0, m.id))
    days = []
    for m in in_week:
        if not days or days[-1]["date"] != m.match_date.isoformat():
            days.append({"date": m.match_date.isoformat(), "date_text": date_text(m.match_date),
                         "is_today": m.match_date == today, "matches": []})
        days[-1]["matches"].append(public_dict(m))

    return {
        "monday": chosen.isoformat(),
        "range_text": week_range_text(chosen),
        "is_current": chosen == this_monday,
        "days": days,
        "prev_url": f"/matches?week={earlier[-1].isoformat()}" if earlier else None,
        "next_url": f"/matches?week={later[0].isoformat()}" if later else None,
        "current_url": None if chosen == this_monday else "/matches",
        "has_any": bool(matches),
    }


def build_team_matches(team, season_end, today=None):
    """Всички кръгове на отбора през сезона (за страницата на отбора). Следващият мач е отбелязан."""
    today = today or today_sofia()
    items = sort_matches(Match.query.filter_by(team_id=team.id, season_end=season_end).all())
    result = [public_dict(m) for m in items]
    for entry in result:
        entry["is_next"] = False
    for entry in result:
        if entry["status"] == MATCH_SCHEDULED and entry["date"] and entry["date"] >= today.isoformat():
            entry["is_next"] = True
            break
    return result
