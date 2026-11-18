import os

from app import create_app

app = create_app()


def debug_enabled(secure_cookies, env=None):
    """Debug режимът на Flask позволява отдалечено изпълнение на код: изключен е по подразбиране, включва се
    само изрично (FLASK_DEBUG=1, локално) и никога при production настройки (SESSION_COOKIE_SECURE=1)."""
    env = os.environ if env is None else env
    return env.get("FLASK_DEBUG") == "1" and not secure_cookies


if __name__ == "__main__":
    # САМО за локална разработка. На сървъра приложението се пуска през WSGI (cPanel/gunicorn), не през този файл.
    app.run(debug=debug_enabled(app.config["SESSION_COOKIE_SECURE"]), port=5000)
