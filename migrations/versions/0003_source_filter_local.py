"""Add filter_local flag to sources.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sources",
        sa.Column("filter_local", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("sources", "filter_local")
