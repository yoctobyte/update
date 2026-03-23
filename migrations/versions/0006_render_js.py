"""Add render_js and cookie_accept_selector to sources.

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sources",
        sa.Column("render_js", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sources",
        sa.Column("cookie_accept_selector", sa.String(300), nullable=True),
    )


def downgrade():
    op.drop_column("sources", "cookie_accept_selector")
    op.drop_column("sources", "render_js")
