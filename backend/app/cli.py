"""Command line tools for the main administrator account.

    flask --app run create-owner <username>   # first start / new server
    flask --app run reset-password <username> # forgotten password (no email recovery)
    flask --app run list-users
"""
import click

from app import db
from app.models import ROLE_OWNER, AdminUser


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
