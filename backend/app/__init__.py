import os

from flask import Flask, redirect, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

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
    }
    with db.engine.begin() as conn:
        for name, ddl in wanted.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE registrations ADD COLUMN {name} {ddl}"))


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

    from app.routes.uploads import files_bp, uploads_bp
    app.register_blueprint(uploads_bp, url_prefix="/api")  # POST /api/admin/uploads
    app.register_blueprint(files_bp)  # GET /uploads/<file>

    @app.errorhandler(413)
    def too_large(_err):
        from flask import jsonify
        return jsonify({"ok": False, "error": "Файлът е твърде голям (до 10 MB)."}), 413

    with app.app_context():
        db.create_all()
        _add_missing_registration_columns()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

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
        # Lets /styles.css, /script.js, /hero-background.css,
        # /assets/... resolve directly, same as on a normal static host.
        return send_from_directory(frontend_dir, filename)

    return app
