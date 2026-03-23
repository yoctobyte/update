from datetime import datetime, timezone
from ..extensions import db


class StoryMergeLog(db.Model):
    __tablename__ = "story_merge_logs"

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("articles.id"), nullable=False, index=True)
    story_id = db.Column(db.Integer, db.ForeignKey("stories.id"), nullable=False, index=True)
    similarity_score = db.Column(db.Float, nullable=False)
    action = db.Column(db.String(20), nullable=False)    # 'auto_merged' | 'suggested' | 'ignored'
    outcome = db.Column(db.String(20), nullable=False, default="pending")  # 'pending' | 'merged' | 'rejected' | 'untied'
    resolved_by = db.Column(db.String(10), nullable=False, default="system")  # 'system' | 'admin'
    resolved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    article = db.relationship("Article", back_populates="merge_logs")
    story = db.relationship("Story", back_populates="merge_logs")

    def __repr__(self):
        return f"<StoryMergeLog article={self.article_id} story={self.story_id} score={self.similarity_score:.3f}>"
