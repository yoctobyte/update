from datetime import datetime, timezone
from ..extensions import db
from .associations import article_topics, story_topics, event_topics


class Topic(db.Model):
    __tablename__ = "topics"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # frontpage_rule: always_in | always_out | depends (default)
    frontpage_rule = db.Column(db.String(12), nullable=False, default="depends")
    # Section sidebar visibility — which nav sections show this topic as a filter
    show_local    = db.Column(db.Boolean, nullable=False, default=True)
    show_region   = db.Column(db.Boolean, nullable=False, default=True)
    show_province = db.Column(db.Boolean, nullable=False, default=True)
    show_national = db.Column(db.Boolean, nullable=False, default=True)
    show_intl     = db.Column(db.Boolean, nullable=False, default=True)
    show_alles    = db.Column(db.Boolean, nullable=False, default=True)
    # Cached article count — updated by the refresh_topic_counts scheduler job
    article_count = db.Column(db.Integer, nullable=False, default=0)

    articles = db.relationship("Article", secondary=article_topics, back_populates="topics")
    stories = db.relationship("Story", secondary=story_topics, back_populates="topics")
    events = db.relationship("Event", secondary=event_topics, back_populates="topics")

    def __repr__(self):
        return f"<Topic {self.name}>"
