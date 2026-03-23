"""Add watched_urls table.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "watched_urls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.String(1000), nullable=False, unique=True),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("watched_urls")
