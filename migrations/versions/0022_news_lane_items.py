"""Add news_lane_items table for Vandaag and Week lanes.

Revision ID: 0022
Revises: 4c826e76d443
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "4c826e76d443"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "news_lane_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lane", sa.String(10), nullable=False),          # 'today' | 'week'
        sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id"), nullable=True),
        sa.Column("story_id", sa.Integer, sa.ForeignKey("stories.id"), nullable=True),
        sa.Column("window_start", sa.DateTime, nullable=True),
        sa.Column("window_end", sa.DateTime, nullable=True),
        sa.Column("rank_score", sa.Float, nullable=True),
        sa.Column("freshness_score", sa.Float, nullable=True),
        sa.Column("blend_score", sa.Float, nullable=True),
        sa.Column("wins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer, nullable=False, server_default="0"),
        sa.Column("similars", sa.Integer, nullable=False, server_default="0"),
        sa.Column("preference_wins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("preference_losses", sa.Integer, nullable=False, server_default="0"),
        sa.Column("comparisons", sa.Integer, nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime, nullable=True),
        sa.Column("removed_at", sa.DateTime, nullable=True),
        sa.Column("pinned", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("suppressed", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("editorial_note", sa.Text, nullable=True),
    )
    op.create_index("ix_news_lane_items_lane", "news_lane_items", ["lane"])
    op.create_index("ix_news_lane_items_article_id", "news_lane_items", ["article_id"])
    op.create_index("ix_news_lane_items_story_id", "news_lane_items", ["story_id"])
    op.create_index("ix_news_lane_items_removed_at", "news_lane_items", ["removed_at"])


def downgrade():
    op.drop_index("ix_news_lane_items_removed_at", "news_lane_items")
    op.drop_index("ix_news_lane_items_story_id", "news_lane_items")
    op.drop_index("ix_news_lane_items_article_id", "news_lane_items")
    op.drop_index("ix_news_lane_items_lane", "news_lane_items")
    op.drop_table("news_lane_items")
