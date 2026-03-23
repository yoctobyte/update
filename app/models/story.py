from datetime import datetime, timezone
from ..extensions import db
from .associations import article_stories, story_topics


class Story(db.Model):
    __tablename__ = "stories"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=True)
    further_reading = db.Column(db.Text, nullable=True)  # free text with topic/link refs
    status = db.Column(db.String(10), nullable=False, default="active")  # 'active' | 'archived'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    articles = db.relationship("Article", secondary=article_stories, back_populates="stories")
    topics = db.relationship("Topic", secondary=story_topics, back_populates="stories")
    merge_logs = db.relationship("StoryMergeLog", back_populates="story", lazy="dynamic")

    def __repr__(self):
        return f"<Story {self.id} {self.title[:40]}>"
