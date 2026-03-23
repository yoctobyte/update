from datetime import datetime, timezone
from ..extensions import db
from .associations import article_topics, story_topics, event_topics


class Topic(db.Model):
    __tablename__ = "topics"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    articles = db.relationship("Article", secondary=article_topics, back_populates="topics")
    stories = db.relationship("Story", secondary=story_topics, back_populates="topics")
    events = db.relationship("Event", secondary=event_topics, back_populates="topics")

    def __repr__(self):
        return f"<Topic {self.name}>"
