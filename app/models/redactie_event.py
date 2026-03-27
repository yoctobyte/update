from datetime import datetime, timezone
from ..extensions import db


class RedactieEvent(db.Model):
    __tablename__ = "redactie_events"

    # Class-level flag — lets templates/views duck-type alongside scraped Event objects
    is_redactie = True

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    location = db.Column(db.String(300))
    start_time = db.Column(db.DateTime, nullable=False, index=True)
    end_time = db.Column(db.DateTime)
    organizer = db.Column(db.String(200))
    contact_info = db.Column(db.String(300))
    source_url = db.Column(db.String(1000))
    published = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    topics = db.relationship(
        "Topic",
        secondary="redactie_event_topics",
        backref=db.backref("redactie_events", lazy="dynamic"),
    )

    def __repr__(self):
        return f"<RedactieEvent {self.id} {self.title[:40]}>"
