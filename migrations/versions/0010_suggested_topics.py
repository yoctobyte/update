"""Add suggested_topics and suggested_topic_articles tables.

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "suggested_topics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("article_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_suggested_topics_name", "suggested_topics", ["name"])
    op.create_index("ix_suggested_topics_status", "suggested_topics", ["status"])

    op.create_table(
        "suggested_topic_articles",
        sa.Column("suggested_topic_id", sa.Integer, sa.ForeignKey("suggested_topics.id"), primary_key=True),
        sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id"), primary_key=True),
    )


def downgrade():
    op.drop_table("suggested_topic_articles")
    op.drop_table("suggested_topics")
