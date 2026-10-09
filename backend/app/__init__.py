from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

db = SQLAlchemy()


def create_app(config_object="config.Config"):
    """Application factory. Keeps setup in one place so we can add
    blueprints (news, teams, auth, ...) here as the project grows."""
    app = Flask(__name__)
    app.config.from_object(config_object)

    db.init_app(app)

    # Allow the static frontend (served from a different origin during
    # local dev, e.g. the file:// or a simple http.server on another
    # port) to call the API.
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    from app.routes.registration import registration_bp
    app.register_blueprint(registration_bp, url_prefix="/api")

    with app.app_context():
        db.create_all()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app
