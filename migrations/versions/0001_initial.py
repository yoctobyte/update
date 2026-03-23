"""Initial schema — sources with new type model, no produces/feed_url

Revision ID: 0001
Revises:
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_topics_name", "topics", ["name"])

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("type", sa.String(20), nullable=False, server_default="link_page"),
        sa.Column("search_depth", sa.Integer, nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_successful_fetch", sa.DateTime, nullable=True),
        sa.Column("last_content_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "extraction_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("rule_type", sa.String(20), nullable=False),
        sa.Column("rule_definition", sa.Text, nullable=False),
        sa.Column("rule_purpose", sa.String(10), nullable=False, server_default="content"),
        sa.Column("approved", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("scope", sa.String(10), nullable=False, server_default="persistent"),
        sa.Column("valid_from", sa.DateTime, nullable=True),
        sa.Column("valid_until", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_extraction_rules_source_id", "extraction_rules", ["source_id"])

    op.create_table(
        "stories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("further_reading", sa.Text, nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "articles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("extracted_text", sa.Text, nullable=True),
        sa.Column("short_text", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("embedding", sa.LargeBinary, nullable=True),
        sa.Column("published_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("hash", sa.String(64), nullable=False, unique=True),
    )
    op.create_index("ix_articles_source_id", "articles", ["source_id"])
    op.create_index("ix_articles_published_at", "articles", ["published_at"])
    op.create_index("ix_articles_created_at", "articles", ["created_at"])
    op.create_index("ix_articles_hash", "articles", ["hash"], unique=True)

    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("location", sa.String(300), nullable=True),
        sa.Column("start_time", sa.DateTime, nullable=False),
        sa.Column("end_time", sa.DateTime, nullable=True),
        sa.Column("organizer", sa.String(200), nullable=True),
        sa.Column("contact_info", sa.String(300), nullable=True),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_events_start_time", "events", ["start_time"])

    op.create_table(
        "story_merge_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("story_id", sa.Integer, sa.ForeignKey("stories.id"), nullable=False),
        sa.Column("similarity_score", sa.Float, nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("resolved_by", sa.String(10), nullable=False, server_default="system"),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_story_merge_logs_article_id", "story_merge_logs", ["article_id"])
    op.create_index("ix_story_merge_logs_story_id", "story_merge_logs", ["story_id"])
    op.create_index("ix_story_merge_logs_created_at", "story_merge_logs", ["created_at"])

    # Junction tables
    op.create_table(
        "article_topics",
        sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id"), primary_key=True),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id"), primary_key=True),
    )
    op.create_table(
        "article_stories",
        sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id"), primary_key=True),
        sa.Column("story_id", sa.Integer, sa.ForeignKey("stories.id"), primary_key=True),
    )
    op.create_table(
        "story_topics",
        sa.Column("story_id", sa.Integer, sa.ForeignKey("stories.id"), primary_key=True),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id"), primary_key=True),
    )
    op.create_table(
        "event_topics",
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id"), primary_key=True),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id"), primary_key=True),
    )
    op.create_table(
        "event_articles",
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id"), primary_key=True),
        sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id"), primary_key=True),
    )

    # sqlite-vec virtual table for article embeddings (384-dim float32)
    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS article_embeddings "
        "USING vec0(article_id INTEGER PRIMARY KEY, embedding FLOAT[384])"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS article_embeddings")
    op.drop_table("event_articles")
    op.drop_table("event_topics")
    op.drop_table("story_topics")
    op.drop_table("article_stories")
    op.drop_table("article_topics")
    op.drop_table("story_merge_logs")
    op.drop_table("events")
    op.drop_table("articles")
    op.drop_table("stories")
    op.drop_table("extraction_rules")
    op.drop_table("sources")
    op.drop_table("topics")
