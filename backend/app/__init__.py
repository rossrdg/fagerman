from flask import Flask, send_from_directory
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

    db.init_app(app)

    # Allow the static frontend to call the API even if it's ever served
    # from a different origin/port than this Flask app.
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    from app.routes.registration import registration_bp
    app.register_blueprint(registration_bp, url_prefix="/api")

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
        # Lets /styles.css, /script.js, /hero-background.css,
        # /assets/... resolve directly, same as on a normal static host.
        return send_from_directory(frontend_dir, filename)

    return app
