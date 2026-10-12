import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from flask import current_app

WEEKDAYS_BG = ["понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя"]


class MailError(Exception):
    """Raised when the SMTP server could not be reached or rejected the mail."""


def build_trial_training_email(registration):
    """Returns (subject, body) with the registration's data filled in."""
    d = registration.training_date
    t = registration.training_time
    day = f"{d:%d.%m.%Y} г. ({WEEKDAYS_BG[d.weekday()]})"
    time = f"{t:%H:%M} ч."

    subject = "Пробна тренировка във Футболна Академия Герман"
    body = (
        f"Здравейте {registration.parent_name},\n"
        "\n"
        "Искаме да Ви уведомим, че "
        f"{registration.child_name} е записан за пробна тренировка във "
        f"Футболна Академия Герман на {day} от {time}\n"
        "\n"
        "Детето да е с подходящо спортно облекло.\n"
        "\n"
        "Ще Ви очакваме.\n"
        "\n"
        "С уважение,\n"
        "Футболна Академия Герман\n"
    )
    return subject, body


def send_email(to_addr, subject, body):
    """Sends a plain-text email. Returns True if really sent, False in dry-run
    mode (no MAIL_SERVER configured). Raises MailError on SMTP problems."""
    cfg = current_app.config
    server = cfg.get("MAIL_SERVER")

    if not server:
        current_app.logger.warning(
            "MAIL_SERVER not set — dry run, email NOT sent.\nTo: %s\nSubject: %s\n\n%s",
            to_addr, subject, body,
        )
        return False

    from_addr = cfg.get("MAIL_FROM") or cfg.get("MAIL_USERNAME")
    if not from_addr:
        raise MailError("MAIL_FROM / MAIL_USERNAME is not configured")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg.get("MAIL_FROM_NAME", ""), from_addr))
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1])
    if cfg.get("MAIL_REPLY_TO"):
        msg["Reply-To"] = cfg["MAIL_REPLY_TO"]
    msg.set_content(body, charset="utf-8")

    port = cfg["MAIL_PORT"]
    try:
        if cfg["MAIL_USE_SSL"]:
            smtp = smtplib.SMTP_SSL(server, port, timeout=15, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(server, port, timeout=15)
        with smtp:
            if cfg["MAIL_USE_TLS"] and not cfg["MAIL_USE_SSL"]:
                smtp.starttls(context=ssl.create_default_context())
            if cfg.get("MAIL_USERNAME"):
                smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(str(exc)) from exc

    return True
