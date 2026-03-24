"""Add extract_attempts and skip_extraction to articles.

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("articles", sa.Column("extract_attempts", sa.Integer, nullable=False, server_default="0"))
    op.add_column("articles", sa.Column("skip_extraction", sa.Boolean, nullable=False, server_default="0"))


def downgrade():
    op.drop_column("articles", "skip_extraction")
    op.drop_column("articles", "extract_attempts")
