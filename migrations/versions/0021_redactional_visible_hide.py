"""Add visible and hide columns to redactional_posts.

visible (default True)  — if False, post is not injected into section feeds
                          even when pinned.
hide    (default False) — if True, post is not shown on the /redactie list
                          or detail page.

Revision ID: 0021
Revises: 0020
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("redactional_posts",
        sa.Column("visible", sa.Boolean, nullable=False, server_default="1"))
    op.add_column("redactional_posts",
        sa.Column("hide", sa.Boolean, nullable=False, server_default="0"))


def downgrade():
    op.drop_column("redactional_posts", "hide")
    op.drop_column("redactional_posts", "visible")
