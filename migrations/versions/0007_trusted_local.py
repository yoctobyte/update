"""Add trusted_local to sources.

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sources",
        sa.Column("trusted_local", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("sources", "trusted_local")
