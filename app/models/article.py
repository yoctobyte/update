from datetime import datetime, timezone
from ..extensions import db
from .associations import article_topics, article_stories, event_articles


class Article(db.Model):
    __tablename__ = "articles"

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("sources.id"), nullable=False, index=True)
    url = db.Column(db.String(1000), nullable=False, index=True)  # ix_articles_url: _primary_only dedup + _sources_by_url
    title = db.Column(db.String(500), nullable=False)
    extracted_text = db.Column(db.Text, nullable=True)
    short_text = db.Column(db.Text, nullable=True)  # ~300 char normalized snippet
    summary = db.Column(db.Text, nullable=True, index=True)  # ix: IS NOT NULL filter in listings + extract queue
    embedding = db.Column(db.LargeBinary, nullable=True)  # raw float32 bytes
    published_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    hash = db.Column(db.String(64), unique=True, nullable=False, index=True)  # SHA-256 of URL
    # geo_scope: null = not yet classified (pending extraction); set by LLM after rewrite.
    # Values: "local", "region", "province", "national", "intl"
    geo_scope = db.Column(db.String(10), nullable=True, index=True)
    # extraction tracking: how many times we tried; skip_extraction = give up permanently
    extract_attempts = db.Column(db.Integer, nullable=False, default=0)
    skip_extraction  = db.Column(db.Boolean, nullable=False, default=False, index=True)  # ix: extract queue scan
    # frontpage worthiness: NULL=not evaluated, True=worthy, False=not worthy (LLM verdict)
    frontpage_worthy = db.Column(db.Boolean, nullable=True)

    __table_args__ = (
        # Composite index for main listing: WHERE geo_scope=? AND summary IS NOT NULL ORDER BY published_at DESC
        db.Index("ix_articles_geo_published", "geo_scope", "published_at"),
    )

    source = db.relationship("Source", back_populates="articles")
    topics = db.relationship("Topic", secondary=article_topics, back_populates="articles")
    stories = db.relationship("Story", secondary=article_stories, back_populates="articles")
    events = db.relationship("Event", secondary=event_articles, back_populates="articles")
    merge_logs = db.relationship("StoryMergeLog", back_populates="article", lazy="dynamic")

    def __repr__(self):
        return f"<Article {self.id} {self.title[:40]}>"
