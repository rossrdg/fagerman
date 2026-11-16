"""Футболисти: отбор по година на раждане, временна парола, речници за API."""
import re
import secrets
from datetime import date

from app import db
from app.models import KIND_YOUTH, TEAM_ACTIVE, Team
from app.team_utils import cohort_text, u_label

STATUS_LABELS = {"active": "Активен", "paused": "В пауза", "left": "Напуснал"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Без символи, които се бъркат (0/O, 1/l/I).
_PASSWORD_CHARS = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_temp_password(length=10):
    return "".join(secrets.choice(_PASSWORD_CHARS) for _ in range(length))


def team_for_birth_year(year):
    """Активният възрастов отбор, чийто набор съдържа годината, или None."""
    for team in Team.query.filter_by(kind=KIND_YOUTH, status=TEAM_ACTIVE).all():
        if team.birth_year_from is not None and team.birth_year_from <= year <= (team.birth_year_to or team.birth_year_from):
            return team
    return None


def player_team(player):
    """(отбор или None, дали е зададен ръчно)."""
    if player.team_override_id and player.team_override is not None:
        return player.team_override, True
    return team_for_birth_year(player.birth_date.year), False


def _team_part(player, season_end):
    team, manual = player_team(player)
    return {
        "team_id": team.id if team else None,
        "team_label": u_label(team, season_end) if team else "",
        "team_cohort": cohort_text(team) if team else "",
        "team_url": f"/teams/{team.slug}" if team else None,
        "team_manual": manual,
    }


def _iso(value):
    return value.isoformat() if value else None


def player_dict(player, season_end, manager=False):
    """Речник за админ API. Без manager=True липсват родителските данни и вътрешните бележки
    (така ги вижда обикновен треньор)."""
    data = {
        "id": player.id,
        "child_name": player.child_name,
        "birth_date": _iso(player.birth_date),
        "status": player.status,
        "status_label": STATUS_LABELS.get(player.status, player.status),
        "archived": bool(player.archived),
        "start_date": _iso(player.start_date),
    }
    data.update(_team_part(player, season_end))
    if manager:
        parent = player.parent
        data.update({
            "team_override_id": player.team_override_id,
            "internal_notes": player.internal_notes or "",
            "registration_id": player.registration_id,
            "created_by": player.created_by,
            "created_at": _iso(player.created_at),
            "parent": {
                "id": parent.id, "name": parent.display_name, "email": parent.email, "phone": parent.phone,
                "is_active": bool(parent.is_active),
                "last_login_at": _iso(parent.last_login_at),
                "must_change_password": bool(parent.must_change_password),
                "consent_at": _iso(parent.consent_at),
            },
        })
    return data


def parent_child_dict(player, season_end):
    """Какво вижда родителят за детето си (без вътрешни бележки и данни на други хора)."""
    data = {
        "id": player.id,
        "child_name": player.child_name,
        "status": player.status,
        "status_label": STATUS_LABELS.get(player.status, player.status),
        "start_date": _iso(player.start_date),
    }
    team = _team_part(player, season_end)
    data.update({k: team[k] for k in ("team_label", "team_cohort", "team_url")})
    return data


def parse_date(value, earliest_year=1940):
    """date от „ГГГГ-ММ-ДД“; ValueError при грешка."""
    if not isinstance(value, str):
        raise ValueError
    parsed = date.fromisoformat(value.strip())
    if not earliest_year <= parsed.year <= 2100:
        raise ValueError
    return parsed
