"""Add redactional_posts table for editorial content.

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "redactional_posts",
        sa.Column("id",            sa.Integer,     primary_key=True),
        sa.Column("topic",         sa.String(100), nullable=False, server_default="nieuws"),
        sa.Column("title",         sa.String(500), nullable=False),
        sa.Column("content",       sa.Text,        nullable=True),
        sa.Column("image_path",    sa.String(500), nullable=True),
        sa.Column("image_alt",     sa.String(500), nullable=True),
        sa.Column("footer",        sa.String(200), nullable=False, server_default="van de redactie"),
        sa.Column("published_at",  sa.DateTime,    nullable=False),
        sa.Column("created_at",    sa.DateTime,    nullable=False),
        sa.Column("pinned",        sa.Boolean,     nullable=False, server_default="0"),
        sa.Column("pin_position",  sa.Integer,     nullable=True),
        sa.Column("pin_expires_at",sa.DateTime,    nullable=True),
        sa.Column("pin_frontpage", sa.Boolean,     nullable=False, server_default="0"),
        sa.Column("pin_lokaal",    sa.Boolean,     nullable=False, server_default="0"),
        sa.Column("pin_alles",     sa.Boolean,     nullable=False, server_default="0"),
        sa.Column("pin_regio",     sa.Boolean,     nullable=False, server_default="0"),
        sa.Column("pin_provincie", sa.Boolean,     nullable=False, server_default="0"),
        sa.Column("pin_nationaal", sa.Boolean,     nullable=False, server_default="0"),
        sa.Column("pin_intl",      sa.Boolean,     nullable=False, server_default="0"),
    )
    op.create_index("ix_redactional_posts_published_at", "redactional_posts", ["published_at"])
    op.create_index("ix_redactional_posts_pinned",       "redactional_posts", ["pinned"])


def downgrade():
    op.drop_index("ix_redactional_posts_pinned",       "redactional_posts")
    op.drop_index("ix_redactional_posts_published_at", "redactional_posts")
    op.drop_table("redactional_posts")
