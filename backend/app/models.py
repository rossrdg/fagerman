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
