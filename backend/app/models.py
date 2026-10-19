from datetime import datetime, timezone

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
