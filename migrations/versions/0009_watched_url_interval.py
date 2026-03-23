"""Add fetch_interval_hours, is_rss, and render_js to watched_urls.

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("watched_urls") as batch_op:
        batch_op.add_column(sa.Column("is_rss", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("fetch_interval_hours", sa.Integer(), nullable=False, server_default="6"))
        batch_op.add_column(sa.Column("render_js", sa.Boolean(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("watched_urls") as batch_op:
        batch_op.drop_column("render_js")
        batch_op.drop_column("fetch_interval_hours")
        batch_op.drop_column("is_rss")
