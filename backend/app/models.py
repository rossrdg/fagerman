from datetime import datetime, timezone

from app import db


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
