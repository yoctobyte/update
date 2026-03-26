"""Add cached article_count to topics.

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("topics", sa.Column("article_count", sa.Integer, nullable=False, server_default="0"))


def downgrade():
    op.drop_column("topics", "article_count")
