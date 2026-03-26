"""Add per-topic section visibility flags.

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_COLUMNS = ["show_local", "show_region", "show_province", "show_national", "show_intl", "show_alles"]


def upgrade():
    for col in _COLUMNS:
        op.add_column("topics", sa.Column(col, sa.Boolean, nullable=False, server_default="1"))


def downgrade():
    for col in _COLUMNS:
        op.drop_column("topics", col)
