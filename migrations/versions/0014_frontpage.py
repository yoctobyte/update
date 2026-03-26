"""Add frontpage feature: per-topic rules, article worthiness, frontpage_items, site_settings.

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    # Per-topic rule: always_in / always_out / depends
    op.add_column("topics", sa.Column(
        "frontpage_rule",
        sa.String(12),
        nullable=False,
        server_default="depends",
    ))

    # Per-article LLM verdict: NULL=not evaluated, 1=worthy, 0=not worthy
    op.add_column("articles", sa.Column(
        "frontpage_worthy",
        sa.Boolean,
        nullable=True,
    ))

    # Historical record of every article that ever appeared on the front page
    op.create_table(
        "frontpage_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("added_at", sa.DateTime, nullable=False),
        sa.Column("removed_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_frontpage_items_article_id", "frontpage_items", ["article_id"])
    op.create_index("ix_frontpage_items_removed_at", "frontpage_items", ["removed_at"])

    # Simple key/value store for persistent site settings
    op.create_table(
        "site_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text, nullable=False, server_default=""),
    )

    # Seed the frontpage_enabled flag to off
    op.execute("INSERT INTO site_settings (key, value) VALUES ('frontpage_enabled', '0')")


def downgrade():
    op.execute("DELETE FROM site_settings WHERE key = 'frontpage_enabled'")
    op.drop_table("site_settings")
    op.drop_index("ix_frontpage_items_removed_at", "frontpage_items")
    op.drop_index("ix_frontpage_items_article_id", "frontpage_items")
    op.drop_table("frontpage_items")
    op.drop_column("articles", "frontpage_worthy")
    op.drop_column("topics", "frontpage_rule")
