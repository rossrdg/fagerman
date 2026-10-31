from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.news_utils import make_excerpt


class Registration(db.Model):
    __tablename__ = "registrations"

    id = db.Column(db.Integer, primary_key=True)
    child_name = db.Column(db.String(120), nullable=False)
    child_age = db.Column(db.Integer, nullable=False)
    parent_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Admin-only fields: not collected from the parent. The admin reviews the
    # request, picks the day/time for the trial training and marks it processed.
    training_date = db.Column(db.Date, nullable=True)
    training_time = db.Column(db.Time, nullable=True)
    processed = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    # When the parent was last emailed about the trial training (None = never).
    notified_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "child_name": self.child_name,
            "child_age": self.child_age,
            "parent_name": self.parent_name,
            "phone": self.phone,
            "email": self.email,
            "created_at": self.created_at.isoformat(),
            "training_date": self.training_date.isoformat() if self.training_date else None,
            "training_time": self.training_time.strftime("%H:%M") if self.training_time else None,
            "processed": bool(self.processed),
            "notified_at": self.notified_at.isoformat() if self.notified_at else None,
        }


def thumb_url(url):
    """Photos uploaded through the admin also exist as a smaller <name>-800.jpg
    version (used on the homepage cards). Other addresses are returned as they are."""
    if url and url.startswith("/uploads/") and url.endswith(".jpg"):
        return url[:-4] + "-800.jpg"
    return url


class Post(db.Model):
    """A news / blog article shown in the "Новини" section."""

    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    # Part of the public URL (/news/<slug>). Created once and never changed, so
    # links that were already shared on Facebook keep working after an edit.
    slug = db.Column(db.String(100), nullable=False, unique=True, index=True)
    excerpt = db.Column(db.String(300), nullable=False, default="")
    body = db.Column(db.Text, nullable=False, default="")  # sanitized HTML
    category = db.Column(db.String(40), nullable=True)
    cover_image = db.Column(db.String(255), nullable=True)
    youtube_id = db.Column(db.String(11), nullable=True)
    status = db.Column(db.String(10), nullable=False, default="draft", server_default="draft")
    published_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self, full=False, admin=False):
        data = {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "url": f"/news/{self.slug}",
            "excerpt": self.excerpt or make_excerpt(self.body),
            "category": self.category,
            "cover_image": self.cover_image,
            "cover_thumb": thumb_url(self.cover_image),
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }
        if full or admin:
            data["body"] = self.body
            data["youtube_id"] = self.youtube_id
        if admin:
            data.update({
                "excerpt": self.excerpt,  # raw value, so the editor shows what was typed
                "status": self.status,
                "youtube_url": f"https://www.youtube.com/watch?v={self.youtube_id}" if self.youtube_id else "",
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            })
        return data


ROLE_OWNER = "owner"  # главен администратор: всичко + управление на акаунти
ROLE_COACH = "coach"  # треньор: само инструментите на админ страниците
ROLE_HEAD_COACH = "head_coach"  # главен треньор: като треньор + управлява треньорите (меню „Треньори“)

_HASH_METHOD = "pbkdf2:sha256"  # работи навсякъде (scrypt не е наличен на всеки хостинг)


def utcnow():
    """Naive UTC time (SQLite does not keep time zones)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AdminUser(db.Model):
    """Account with access to the admin pages. Only the owner can create,
    disable or delete the others (see routes/auth.py)."""

    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), nullable=False, unique=True, index=True)
    display_name = db.Column(db.String(80), nullable=False, default="")
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default=ROLE_COACH)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # Raised on every password change / deactivation: open sessions of the
    # user stop working immediately.
    token_version = db.Column(db.Integer, nullable=False, default=1)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    @property
    def is_owner(self):
        return self.role == ROLE_OWNER

    @property
    def is_head_coach(self):
        return self.role == ROLE_HEAD_COACH

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method=_HASH_METHOD)
        self.token_version = (self.token_version or 0) + 1

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name or self.username,
            "role": self.role,
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


# ------------------------------------------------------------------ teams ---
TEAM_ACTIVE = "active"      # виден на сайта
TEAM_ARCHIVED = "archived"  # скрит от сайта, данните се пазят
KIND_YOUTH = "youth"        # възрастов отбор (U6, U7 ... по набор)
KIND_MEN = "men"            # мъжки отбор


class Setting(db.Model):
    """Малки настройки на сайта (key -> value). Засега: текущият сезон."""

    __tablename__ = "settings"

    key = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.String(200), nullable=False, default="")


class Team(db.Model):
    """Отбор на академията. Идентификатор е НАБОРЪТ (годината на раждане), а
    етикетът U6/U7/... се изчислява според сезона (виж app/team_utils.py)."""

    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    # Част от публичния адрес (/teams/<slug>): "2020", "2014-2015", "men".
    # Създава се веднъж и не се променя, за да не се чупят споделени линкове.
    slug = db.Column(db.String(30), nullable=False, unique=True, index=True)
    kind = db.Column(db.String(10), nullable=False, default=KIND_YOUTH)
    # Набор: една година (to = NULL) или две (напр. 2014 и 2015). "from" е
    # по-старата година — от нея се смята U етикетът. Мъжкият отбор няма набор.
    birth_year_from = db.Column(db.Integer, nullable=True)
    birth_year_to = db.Column(db.Integer, nullable=True)
    # Ръчно зададен етикет; ако е празен, етикетът се изчислява автоматично.
    u_override = db.Column(db.String(12), nullable=True)
    description = db.Column(db.String(160), nullable=False, default="")
    status = db.Column(db.String(10), nullable=False, default=TEAM_ACTIVE, server_default=TEAM_ACTIVE)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------- schedule ---
# Връзка „слот <-> отбор“: един слот може да е за няколко отбора (напр. обща
# тренировъчна група 2018/19 за U8 и U9).
slot_teams = db.Table(
    "training_slot_teams",
    db.Column("slot_id", db.Integer, db.ForeignKey("training_slots.id", ondelete="CASCADE"), primary_key=True),
    db.Column("team_id", db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True),
)


class TrainingSlot(db.Model):
    """Един ред от седмичния тренировъчен график: ден + час + кой тренира."""

    __tablename__ = "training_slots"

    id = db.Column(db.Integer, primary_key=True)
    weekday = db.Column(db.Integer, nullable=False)     # 1 = понеделник ... 7 = неделя
    start_time = db.Column(db.String(5), nullable=False)  # "18:30"
    # Свободен текст (напр. „Вратари — големи“). Ползва се само ако няма отбори.
    label = db.Column(db.String(40), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    teams = db.relationship("Team", secondary=slot_teams, backref=db.backref("training_slots", lazy="select"))
    # Групи без отбор (напр. „Вратари — големи“) — виж TrainingGroup
    groups = db.relationship("TrainingGroup", secondary="training_slot_groups",
                             backref=db.backref("training_slots", lazy="select"))


# ---------------------------------------------------------------- gallery ---
class Album(db.Model):
    """Албум със снимки от събитие (турнир, мач, тренировка) на един отбор."""

    __tablename__ = "albums"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(80), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    is_hidden = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    # Избрана корица; ако е празно (или снимката е изтрита), корица е най-новата снимка.
    cover_photo_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    team = db.relationship("Team", backref=db.backref("albums", cascade="all, delete-orphan"))
    photos = db.relationship("Photo", backref="album", cascade="all, delete-orphan",
                             order_by="Photo.id.desc()")


class Photo(db.Model):
    """Снимка в албум. Качването й от треньор означава, че има съгласие на родителите."""

    __tablename__ = "photos"

    id = db.Column(db.Integer, primary_key=True)
    album_id = db.Column(db.Integer, db.ForeignKey("albums.id", ondelete="CASCADE"), nullable=False, index=True)
    # Случайно име на файла (без разширение): /uploads/<name>.jpg и <name>-800.jpg
    name = db.Column(db.String(20), nullable=False, unique=True)
    # Номер за справка ДДММГГ + 3 случайни цифри, напр. 271026482. Без имена на деца.
    code = db.Column(db.String(9), nullable=False, unique=True, index=True)
    uploaded_by = db.Column(db.String(80), nullable=False, default="")  # кой е качил (не се показва публично)
    created_at = db.Column(db.DateTime, default=utcnow)


class Video(db.Model):
    """Клип от YouTube към отбор (само линк, нищо не се качва)."""

    __tablename__ = "videos"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    youtube_id = db.Column(db.String(11), nullable=False)
    title = db.Column(db.String(80), nullable=False, default="")
    added_by = db.Column(db.String(80), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=utcnow)

    team = db.relationship("Team", backref=db.backref("videos", cascade="all, delete-orphan"))


# ------------------------------------------------------ история на сезоните ---
class SeasonSwitch(db.Model):
    """Една смяна на сезона. Пази се цялата история, за да може да се върне
    всеки предишен сезон (обратно, смяна по смяна)."""

    __tablename__ = "season_switches"

    id = db.Column(db.Integer, primary_key=True)
    from_end = db.Column(db.Integer, nullable=False)  # крайна година на стария сезон (напр. 2027 за 2026/27)
    to_end = db.Column(db.Integer, nullable=False)    # крайна година на новия сезон
    archived_ids = db.Column(db.Text, nullable=False, default="[]")  # JSON: отбори, архивирани автоматично (преминали в MEN)
    created_team_id = db.Column(db.Integer, nullable=True)           # отбор, създаден при смяната (нов най-малък набор)
    switched_by = db.Column(db.String(80), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=utcnow)


# ---------------------------------------------------------- профил на треньор ---
# Кои отбори води треньорът (само за показване на сайта, не ограничава достъпа).
coach_teams = db.Table(
    "coach_teams",
    db.Column("profile_id", db.Integer, db.ForeignKey("coach_profiles.id", ondelete="CASCADE"), primary_key=True),
    db.Column("team_id", db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True),
)


class CoachProfile(db.Model):
    """Публичният профил на треньор (снимка, биография, отбори). Принадлежи на акаунта:
    изтриването на акаунта изтрива и профила. Изключен акаунт запазва профила си."""

    __tablename__ = "coach_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, unique=True)
    photo_name = db.Column(db.String(20), nullable=True)  # /uploads/<name>.jpg и <name>-800.jpg
    bio = db.Column(db.String(600), nullable=False, default="")
    show_on_site = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship("AdminUser", backref=db.backref("profile", uselist=False, cascade="all, delete-orphan"))
    teams = db.relationship("Team", secondary=coach_teams, backref=db.backref("coach_profiles", lazy="select"))
    groups = db.relationship("TrainingGroup", secondary="coach_groups",
                             backref=db.backref("coach_profiles", lazy="select"))


# ----------------------------------------------- групи без отбор (вратари и др.) ---
class TrainingGroup(db.Model):
    """Тренировъчна група, която не е отбор по набор — напр. „Вратари — големи“.
    Избира се в графика и като „води“ при профила на треньор."""

    __tablename__ = "training_groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=utcnow)


training_slot_groups = db.Table(
    "training_slot_groups",
    db.Column("slot_id", db.Integer, db.ForeignKey("training_slots.id", ondelete="CASCADE"), primary_key=True),
    db.Column("group_id", db.Integer, db.ForeignKey("training_groups.id", ondelete="CASCADE"), primary_key=True),
)

coach_groups = db.Table(
    "coach_groups",
    db.Column("profile_id", db.Integer, db.ForeignKey("coach_profiles.id", ondelete="CASCADE"), primary_key=True),
    db.Column("group_id", db.Integer, db.ForeignKey("training_groups.id", ondelete="CASCADE"), primary_key=True),
)
