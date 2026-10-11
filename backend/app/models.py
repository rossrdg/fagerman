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
    # Not collected from the parent anymore — the admin proposes a date/time
    # after reviewing the request, so these stay nullable until then.
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "child_name": self.child_name,
            "child_age": self.child_age,
            "parent_name": self.parent_name,
            "phone": self.phone,
            "email": self.email,
            "created_at": self.created_at.isoformat(),
        }
