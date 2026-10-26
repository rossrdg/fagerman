"""Command line tools for the main administrator account.

    flask --app run create-owner <username>   # first start / new server
    flask --app run reset-password <username> # forgotten password (no email recovery)
    flask --app run list-users
    flask --app run seed-teams                # първоначално попълване на отборите
"""
import click

from app import db
from app.models import KIND_MEN, KIND_YOUTH, ROLE_OWNER, AdminUser, Team
from app.team_utils import cohort_slug, get_season_end_year

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
