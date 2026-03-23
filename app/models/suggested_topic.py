from datetime import datetime, timezone
from ..extensions import db

# Join table: which articles triggered a given suggestion
suggested_topic_articles = db.Table(
    "suggested_topic_articles",
    db.Column("suggested_topic_id", db.Integer, db.ForeignKey("suggested_topics.id"), primary_key=True),
    db.Column("article_id", db.Integer, db.ForeignKey("articles.id"), primary_key=True),
)


class SuggestedTopic(db.Model):
    __tablename__ = "suggested_topics"

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), unique=True, nullable=False, index=True)
    # pending → admin hasn't acted; approved → became a real Topic; rejected → dismissed
    status     = db.Column(db.String(20), nullable=False, default="pending", index=True)
    article_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    articles = db.relationship("Article", secondary=suggested_topic_articles, lazy="dynamic")

    def __repr__(self):
        return f"<SuggestedTopic {self.name} [{self.status}]>"
