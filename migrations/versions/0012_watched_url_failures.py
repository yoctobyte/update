"""Add consecutive_failures to watched_urls.

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "watched_urls",
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("watched_urls", "consecutive_failures")
