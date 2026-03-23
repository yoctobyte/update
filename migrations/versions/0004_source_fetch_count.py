"""Add last_fetch_new_count to sources.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sources",
        sa.Column("last_fetch_new_count", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("sources", "last_fetch_new_count")
