from datetime import datetime, timezone
from ..extensions import db
from .associations import event_topics, event_articles


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(300), nullable=True)
    start_time = db.Column(db.DateTime, nullable=False, index=True)
    end_time = db.Column(db.DateTime, nullable=True)
    organizer = db.Column(db.String(200), nullable=True)
    contact_info = db.Column(db.String(300), nullable=True)
    source_url = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    topics = db.relationship("Topic", secondary=event_topics, back_populates="events")
    articles = db.relationship("Article", secondary=event_articles, back_populates="events")

    def __repr__(self):
        return f"<Event {self.id} {self.title[:40]}>"
