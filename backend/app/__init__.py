import os

from flask import Flask, redirect, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy.exc import IntegrityError

db = SQLAlchemy()


def _add_missing_registration_columns():
    """db.create_all() never alters an existing table, so databases created
    before the admin columns existed get them added here. Replace with
    Flask-Migrate once the schema starts changing more often."""
    from sqlalchemy import inspect, text

    existing = {c["name"] for c in inspect(db.engine).get_columns("registrations")}
    wanted = {
        "training_date": "DATE",
        "training_time": "TIME",
        "processed": "BOOLEAN NOT NULL DEFAULT 0",
        "notified_at": "DATETIME",
        "player_id": "INTEGER",
    }
    with db.engine.begin() as conn:
        for name, ddl in wanted.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE registrations ADD COLUMN {name} {ddl}"))


def _add_missing_announcement_columns():
    """Известията са създадени преди колоните за имейл; db.create_all() не променя съществуваща таблица."""
    from sqlalchemy import inspect, text

    existing = {c["name"] for c in inspect(db.engine).get_columns("announcements")}
    wanted = {"emailed_at": "DATETIME", "emailed_count": "INTEGER NOT NULL DEFAULT 0"}
    with db.engine.begin() as conn:
        for name, ddl in wanted.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE announcements ADD COLUMN {name} {ddl}"))


def _add_missing_team_columns():
    """Отборите са създадени преди снимката на отбора; db.create_all() не променя съществуваща таблица."""
    from sqlalchemy import inspect, text

    existing = {c["name"] for c in inspect(db.engine).get_columns("teams")}
    if "photo_name" not in existing:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE teams ADD COLUMN photo_name VARCHAR(20)"))


def _make_album_team_optional():
    """Общите албуми нямат отбор (albums.team_id е NULL). db.create_all() не сваля NOT NULL от
    съществуваща таблица, затова колоната се преправя тук. Данните се запазват."""
    from sqlalchemy import inspect, text

    column = next(c for c in inspect(db.engine).get_columns("albums") if c["name"] == "team_id")
    if column.get("nullable", True):
        return
    dialect = db.engine.dialect.name
    if dialect == "sqlite":
        # SQLite не може да смени колона на място: нова таблица -> копиране -> размяна.
        with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("BEGIN"))
            try:
                conn.execute(text(
                    "CREATE TABLE albums__new (id INTEGER NOT NULL, team_id INTEGER, title VARCHAR(80) NOT NULL, "
                    "event_date DATE NOT NULL, is_hidden BOOLEAN NOT NULL DEFAULT 0, cover_photo_id INTEGER, "
                    "created_at DATETIME, updated_at DATETIME, PRIMARY KEY (id), "
                    "FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE)"))
                conn.execute(text(
                    "INSERT INTO albums__new (id, team_id, title, event_date, is_hidden, cover_photo_id, created_at, updated_at) "
                    "SELECT id, team_id, title, event_date, is_hidden, cover_photo_id, created_at, updated_at FROM albums"))
                conn.execute(text("DROP TABLE albums"))
                conn.execute(text("ALTER TABLE albums__new RENAME TO albums"))
                conn.execute(text("CREATE INDEX ix_albums_team_id ON albums (team_id)"))
                conn.execute(text("COMMIT"))
            except Exception:
                conn.execute(text("ROLLBACK"))
                raise
    elif dialect in ("mysql", "mariadb"):
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE albums MODIFY team_id INTEGER NULL"))
    elif dialect == "postgresql":
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE albums ALTER COLUMN team_id DROP NOT NULL"))


def create_app(config_object="config.Config"):
    """Application factory. Keeps setup in one place so we can add
    blueprints (news, teams, auth, ...) here as the project grows."""
    app = Flask(
        __name__,
        static_folder=None,  # we register our own static handling below
    )
    app.config.from_object(config_object)

    if app.config["SESSION_COOKIE_SECURE"] and app.config["SECRET_KEY"] == "dev-only-change-me":
        raise RuntimeError("Задайте дълъг случаен SECRET_KEY в backend/.env преди production.")

    db.init_app(app)

    # Allow the static frontend to call the API even if it's ever served
    # from a different origin/port than this Flask app.
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    from app.routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/api")  # login, /api/admin/users

    from app.cli import register_cli
    register_cli(app)

    from app.routes.registration import registration_bp
    app.register_blueprint(registration_bp, url_prefix="/api")

    from app.routes.news import admin_news_bp, news_bp, page_bp
    app.register_blueprint(news_bp, url_prefix="/api")
    app.register_blueprint(admin_news_bp, url_prefix="/api")
    app.register_blueprint(page_bp)  # /news/<slug>

    from app.routes.teams import admin_teams_bp, page_bp as team_page_bp, teams_bp
    app.register_blueprint(teams_bp, url_prefix="/api")  # GET /api/teams
    app.register_blueprint(admin_teams_bp, url_prefix="/api")  # /api/admin/teams
    app.register_blueprint(team_page_bp)  # /teams/<slug>

    from app.routes.schedule import admin_schedule_bp, page_bp as schedule_page_bp
    app.register_blueprint(admin_schedule_bp, url_prefix="/api")  # /api/admin/schedule
    app.register_blueprint(schedule_page_bp)  # /schedule

    from app.routes.gallery import admin_gallery_bp, page_bp as gallery_page_bp
    app.register_blueprint(admin_gallery_bp, url_prefix="/api")  # /api/admin/albums, /photos, /videos
    app.register_blueprint(gallery_page_bp)  # /teams/<slug>/albums/<id>

    from app.routes.coaches import admin_coaches_bp, public_coaches_bp
    app.register_blueprint(admin_coaches_bp, url_prefix="/api")  # /api/admin/coaches
    app.register_blueprint(public_coaches_bp)  # /coaches, /api/coaches/head

    from app.routes.season import admin_season_bp
    app.register_blueprint(admin_season_bp, url_prefix="/api")  # /api/admin/season

    from app.routes.matches import admin_matches_bp, page_bp as matches_page_bp
    app.register_blueprint(matches_page_bp)  # /matches
    app.register_blueprint(admin_matches_bp, url_prefix="/api")  # /api/admin/matches

    from app.routes.sponsors import admin_sponsors_bp, sponsors_bp
    app.register_blueprint(sponsors_bp, url_prefix="/api")  # GET /api/sponsors
    app.register_blueprint(admin_sponsors_bp, url_prefix="/api")  # /api/admin/sponsors

    from app.routes.shop import admin_shop_bp, page_bp as shop_page_bp, shop_api_bp
    app.register_blueprint(shop_page_bp)  # /shop, /privacy
    app.register_blueprint(shop_api_bp, url_prefix="/api")  # /api/shop/orders
    app.register_blueprint(admin_shop_bp, url_prefix="/api")  # /api/admin/shop/products
    from app.routes.parent import parent_bp
    from app.routes.players import admin_players_bp
    app.register_blueprint(parent_bp, url_prefix="/api")  # /api/parent/*
    app.register_blueprint(admin_players_bp, url_prefix="/api")  # /api/admin/players
    from app.routes.documents import admin_docs_bp, parent_docs_bp
    app.register_blueprint(parent_docs_bp, url_prefix="/api")  # /api/parent/documents, /files
    app.register_blueprint(admin_docs_bp, url_prefix="/api")  # /api/admin/documents, /files
    from app.routes.forms import admin_forms_bp, parent_forms_bp
    app.register_blueprint(parent_forms_bp, url_prefix="/api")  # /api/parent/children/<id>/forms/*
    app.register_blueprint(admin_forms_bp, url_prefix="/api")  # /api/admin/settings/club-name
    from app.routes.fees import admin_fees_bp, parent_messages_bp
    app.register_blueprint(admin_fees_bp, url_prefix="/api")  # /api/admin/fee-types, /fees, /fee-charges
    app.register_blueprint(parent_messages_bp, url_prefix="/api")  # /api/parent/messages
    from app.routes.announcements import admin_announcements_bp
    app.register_blueprint(admin_announcements_bp, url_prefix="/api")  # /api/admin/announcements

    from app.routes.uploads import files_bp, uploads_bp
    app.register_blueprint(uploads_bp, url_prefix="/api")  # POST /api/admin/uploads
    app.register_blueprint(files_bp)  # GET /uploads/<file>

    @app.errorhandler(IntegrityError)
    def retry_after_race(_err):
        """Редовете за документи и такси се създават „при отваряне“ на страница. Ако две заявки го направят
        едновременно, втората среща уникално ограничение. Връщаме сесията и изпълняваме заявката още веднъж —
        вторият път редовете вече съществуват. Втори неуспех е истински конфликт (409), не безкраен цикъл."""
        from flask import g, jsonify

        db.session.rollback()
        if g.get("_race_retried"):
            return jsonify({"ok": False, "error": "Конфликт при запис. Опитайте отново."}), 409
        g._race_retried = True
        for cached in ("_admin_user", "_parent"):
            g.pop(cached, None)  # свързани са със сесията, която току-що върнахме
        return app.full_dispatch_request()

    @app.errorhandler(413)
    def too_large(_err):
        from flask import jsonify
        return jsonify({"ok": False, "error": "Файлът е твърде голям (до 20 MB)."}), 413

    with app.app_context():
        db.create_all()
        _add_missing_registration_columns()
        _add_missing_announcement_columns()
        _add_missing_team_columns()
        _make_album_team_optional()
        from app.schedule_utils import migrate_label_slots_to_groups

        migrate_label_slots_to_groups()  # стари слотове „Вратари — …“ -> групи

    @app.get("/api/health")
    def health():
        from app.routes.uploads import HEIC_SUPPORTED

        # "heic": true значи, че pillow-heif е инсталиран и снимките от iPhone се приемат.
        return {"status": "ok", "heic": HEIC_SUPPORTED}

    # --- Serve the static site (index.html, styles.css, script.js, ...) ---
    frontend_dir = app.config["FRONTEND_DIR"]

    @app.get("/")
    def serve_index():
        return send_from_directory(frontend_dir, "index.html")

    @app.get("/<path:filename>")
    def serve_frontend_file(filename):
        # Admin pages are only handed out to logged-in users.
        name = os.path.basename(filename).lower()
        if name.startswith("admin") and name.endswith(".html") and name != "admin-login.html":
            from app.auth import current_user
            user = current_user()
            if user is None:
                return redirect("/admin-login.html")
            if name == "admin-users.html" and not user.is_owner:
                return redirect("/admin-registrations.html")
            if name in ("admin-shop.html", "admin-orders.html", "admin-reports.html") and not (user.is_owner or user.is_head_coach):
                return redirect("/admin-registrations.html")
        # Родителските страници: само за влезли родители; докато паролата не е сменена —
        # единствената достъпна страница е смяната на парола.
        if name.startswith("parent") and name.endswith(".html") and name != "parent-login.html":
            from app.parent_auth import current_parent, parent_pending

            parent = current_parent()
            if parent is None:
                return redirect("/parent-login.html")
            if name != "parent-change-password.html" and parent_pending(parent):
                return redirect("/parent-change-password.html")
        # Lets /styles.css, /script.js, /hero-background.css,
        # /assets/... resolve directly, same as on a normal static host.
        return send_from_directory(frontend_dir, filename)

    return app
