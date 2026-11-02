"""Command line tools for the main administrator account.

    flask --app run create-owner <username>   # first start / new server
    flask --app run reset-password <username> # forgotten password (no email recovery)
    flask --app run list-users
    flask --app run seed-teams                # първоначално попълване на отборите
    flask --app run seed-schedule             # първоначален тренировъчен график
    flask --app run set-season 2027           # ръчно задава сезона (2027 = 2026/27) и чисти историята
    flask --app run import-matches файл.xlsx           # преглед на програмата по кръгове (нищо не записва)
    flask --app run import-matches файл.xlsx --apply   # същото + запис в базата
"""
import click

from app import db
from app.models import (
    KIND_MEN, KIND_YOUTH, MATCH_NOT_PLAYED, MATCH_PLAYED, MATCH_REST, ROLE_OWNER,
    AdminUser, Match, SeasonSwitch, Team, TrainingGroup, TrainingSlot,
)
from app.team_utils import (
    YOUTH_MIN_U, cohort_label, cohort_slug, get_season_end_year, season_text, set_season_end_year, u_label,
)

# (вид, набор от, набор до, кратко описание). Текстовете на U7, U9, U11, U13, U15
# и MEN са взети от досегашната начална страница; тези на U6, U8 и U10 са ЧЕРНОВИ
# — редактират се от админ панела (Отбори).
SEED_TEAMS = [
    (KIND_YOUTH, 2021, None, "Първата среща с топката — чрез игра и усмивки."),
    (KIND_YOUTH, 2020, None, "Първи стъпки във футбола."),
    (KIND_YOUTH, 2019, None, "Основни умения, координация и радост от играта."),
    (KIND_YOUTH, 2018, None, "Техника, игра и увереност."),
    (KIND_YOUTH, 2017, None, "Усъвършенстване на техниката и първи тактически идеи."),
    (KIND_YOUTH, 2016, None, "Развитие на индивидуални качества."),
    (KIND_YOUTH, 2014, 2015, "Тактика и разбиране на играта."),
    (KIND_YOUTH, 2012, 2013, "Конкурентна среда и развитие."),
    (KIND_MEN, None, None, "Футболът продължава."),
]

# Графикът от картинката „График на тренировките“. Всеки ред е
# (ден 1=Пон..7=Нед, час, [набори (slug-ове на отбори)], свободен текст).
# Редът в списъка е редът в клетката на графика.
SEED_SCHEDULE = [
    (1, "17:30", ["2021"], ""), (3, "17:30", ["2021"], ""), (5, "17:30", ["2021"], ""),
    (1, "18:30", ["2016"], ""), (1, "18:30", ["2020"], ""),
    (2, "18:30", [], "Вратари — големи"), (2, "18:30", ["2017"], ""),
    (3, "18:30", ["2016"], ""), (3, "18:30", ["2020"], ""), (3, "18:30", [], "Вратари — малки"),
    (4, "18:30", ["2017"], ""),
    (5, "18:30", ["2016"], ""), (5, "18:30", ["2020"], ""), (5, "18:30", ["2017"], ""),
    (1, "19:00", ["2014-2015"], ""),
    (1, "19:30", ["2018", "2019"], ""), (3, "19:30", ["2018", "2019"], ""), (5, "19:30", ["2018", "2019"], ""),
    (3, "19:30", ["2014-2015"], ""), (5, "19:30", ["2014-2015"], ""),
    (2, "19:30", ["2012-2013"], ""), (4, "19:30", ["2012-2013"], ""),
    (1, "20:00", ["2012-2013"], ""),
]


def register_cli(app):
    @app.cli.command("create-owner")
    @click.argument("username")
    @click.option("--name", default="", help="Показвано име")
    @click.password_option(help="Парола (минимум 8 символа)")
    def create_owner(username, name, password):
        username = username.strip().lower()
        if len(password) < 8:
            raise click.ClickException("Паролата трябва да е поне 8 символа.")
        if AdminUser.query.filter_by(username=username).first():
            raise click.ClickException("Такъв потребител вече съществува.")
        user = AdminUser(username=username, display_name=name or username, role=ROLE_OWNER)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Главен администратор '{username}' е създаден.")

    @app.cli.command("reset-password")
    @click.argument("username")
    @click.password_option(help="Нова парола (минимум 8 символа)")
    def reset_password(username, password):
        user = AdminUser.query.filter_by(username=username.strip().lower()).first()
        if user is None:
            raise click.ClickException("Няма такъв потребител.")
        if len(password) < 8:
            raise click.ClickException("Паролата трябва да е поне 8 символа.")
        user.set_password(password)
        user.is_active = True
        user.failed_attempts = 0
        user.locked_until = None
        db.session.commit()
        click.echo("Паролата е сменена.")

    @app.cli.command("list-users")
    def list_users():
        for u in AdminUser.query.order_by(AdminUser.id):
            state = "активен" if u.is_active else "изключен"
            click.echo(f"{u.id:>3}  {u.username:<20} {u.role:<6} {state}")

    @app.cli.command("seed-teams")
    def seed_teams():
        """Създава отборите U6–U15 и MEN. Безопасно е да се пусне повторно:
        отбор, който вече съществува, не се пипа."""
        get_season_end_year()  # записва текущия сезон в базата
        created = 0
        for kind, year_from, year_to, description in SEED_TEAMS:
            slug = "men" if kind == KIND_MEN else cohort_slug(year_from, year_to)
            if Team.query.filter_by(slug=slug).first():
                continue
            db.session.add(Team(slug=slug, kind=kind, birth_year_from=year_from,
                                birth_year_to=year_to, description=description))
            created += 1
        db.session.commit()
        click.echo(f"Създадени отбори: {created}. Всичко: {Team.query.count()}.")

    @app.cli.command("seed-schedule")
    def seed_schedule():
        """Въвежда тренировъчния график от картинката. Работи само ако още няма
        нито един слот (за да не се дублира и да не се презапишат ваши промени).
        Пускайте го СЛЕД seed-teams."""
        if TrainingSlot.query.count():
            click.echo("Графикът вече има слотове — не пипам нищо.")
            return
        teams = {t.slug: t for t in Team.query.all()}
        missing = {slug for _, _, slugs, _ in SEED_SCHEDULE for slug in slugs if slug not in teams}
        if missing:
            click.echo(f"Липсват отбори: {', '.join(sorted(missing))}. Първо пуснете seed-teams.")
            return
        groups = {}
        for day, time, slugs, group_name in SEED_SCHEDULE:
            slot = TrainingSlot(weekday=day, start_time=time, label="")
            slot.teams = [teams[s] for s in slugs]
            if group_name:  # вратарите са група без отбор
                if group_name not in groups:
                    groups[group_name] = (TrainingGroup.query.filter_by(name=group_name).first()
                                          or TrainingGroup(name=group_name))
                slot.groups = [groups[group_name]]
            db.session.add(slot)
        db.session.commit()
        click.echo(f"Създадени слотове: {TrainingSlot.query.count()}.")

    @app.cli.command("set-season")
    @click.argument("end_year", type=int)
    def set_season(end_year):
        """Ръчно задава текущия сезон (крайната му година: 2027 за 2026/27).

        Нужно е само при оправяне на тестови данни. ЧИСТИ историята на смените
        (после „Върни към…“ в админа започва отначало) и НЕ променя отборите —
        само показва кои трябва да проверите на ръка."""
        if not 2000 <= end_year <= 2100:
            raise click.BadParameter("Въведете крайна година на сезона, напр. 2027.")
        removed = SeasonSwitch.query.delete()
        set_season_end_year(end_year)
        db.session.commit()
        click.echo(f"Сезон: {season_text(end_year)}. Изчистена история на смените: {removed}.")

        archived = [t for t in Team.query.filter_by(status="archived").all()]
        too_young = [
            t for t in Team.query.filter_by(kind=KIND_YOUTH).all()
            if t.birth_year_from is not None and end_year - t.birth_year_from < YOUTH_MIN_U
        ]
        if archived:
            click.echo("Архивирани отбори (възстановете в админа ако трябва): "
                       + ", ".join(cohort_label(t) for t in archived))
        if too_young:
            click.echo("Набори, по-малки от U6 за този сезон (вероятно тестови — архивирайте и изтрийте): "
                       + ", ".join(cohort_label(t) for t in too_young))

    @app.cli.command("import-matches")
    @click.argument("path", type=click.Path(exists=True, dir_okay=False))
    @click.option("--apply", "do_apply", is_flag=True, help="Записва мачовете (без него се показва само преглед).")
    @click.option("--season", type=int, default=None, help="Сезон (крайна година, напр. 2027). По подразбиране — текущият.")
    def import_matches(path, do_apply, season):
        """Зарежда програмата по кръгове от Excel (по един лист на отбор: U8, U9 ... MEN).

        Без --apply само показва какво ще се зареди и какво не се разбира. Мач, който
        вече съществува (същият отбор, сезон и кръг), се пропуска — нищо не се презаписва,
        затова командата е безопасна за повторно пускане. Ако има грешки в редове или листове,
        не се записва нищо, докато не се оправи файлът."""
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise click.ClickException("Липсва openpyxl. Пуснете: pip install -r requirements.txt")
        from app.match_import import parse_sheet, resolve_team

        season_end = season or get_season_end_year()
        workbook = load_workbook(path, data_only=True)
        click.echo(f"Сезон {season_text(season_end)} · файл {path}\n")

        to_create, skipped, problems = [], 0, 0
        for ws in workbook.worksheets:
            team = resolve_team(ws.title, season_end)
            if team is None:
                click.echo(f"=== {ws.title}: ПРОПУСНАТ — няма активен отбор с този етикет през този сезон")
                problems += 1
                continue
            try:
                rows = parse_sheet(ws)
            except ValueError as err:
                click.echo(f"=== {ws.title}: ПРОПУСНАТ — {err}")
                problems += 1
                continue
            click.echo(f"=== {ws.title} -> {u_label(team, season_end)} · {cohort_label(team)} (/teams/{team.slug})")
            existing = {m.round_no for m in Match.query.filter_by(team_id=team.id, season_end=season_end)}
            for row in rows:
                when = row.match_date.strftime("%d.%m.%Y") if row.match_date else "—"
                if row.errors:
                    problems += 1
                    click.echo(f"  ред {row.source_row}: ГРЕШКА — " + "; ".join(row.errors))
                    continue
                if row.status == MATCH_REST:
                    text = "почива"
                else:
                    hour = row.match_time.strftime("%H:%M") if row.match_time else "час предстои"
                    side = "дома " if row.is_home else "гост "
                    text = f"{side}{row.opponent} · {hour}"
                    if row.status == MATCH_NOT_PLAYED:
                        text += " · НЕПРОВЕДЕН"
                    if row.status == MATCH_PLAYED:
                        text += f" · резултат {row.goals_for}:{row.goals_against} (наш:техен)"
                if row.note:
                    text += f" · ({row.note})"
                already = row.round_no in existing
                click.echo(f"  Кръг {row.round_no:>2} · {when} · {text}" + ("   [вече има — пропуска се]" if already else ""))
                for warning in row.warnings:
                    click.echo(f"      ! {warning}")
                if already:
                    skipped += 1
                else:
                    to_create.append((team, row))
            click.echo("")

        click.echo(f"За зареждане: {len(to_create)} · вече съществуват: {skipped} · проблеми: {problems}")
        if problems:
            click.echo("Има проблеми (виж отгоре). Оправете файла и пуснете отново — нищо не е записано.")
            return
        if not do_apply:
            click.echo("Това е само преглед. За запис добавете --apply.")
            return
        for team, row in to_create:
            db.session.add(Match(
                team_id=team.id, season_end=season_end, round_no=row.round_no,
                match_date=row.match_date, match_time=row.match_time, is_home=row.is_home,
                opponent=row.opponent, venue="", status=row.status,
                goals_for=row.goals_for, goals_against=row.goals_against,
                note=row.note, created_by="импорт от Excel", updated_by="импорт от Excel",
            ))
        db.session.commit()
        click.echo(f"Записани мачове: {len(to_create)}.")
