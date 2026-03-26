"""Add http_etag and http_last_modified to sources for conditional GET support.

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sources") as batch_op:
        batch_op.add_column(sa.Column("http_etag", sa.String(500), nullable=True))
        batch_op.add_column(sa.Column("http_last_modified", sa.String(200), nullable=True))


def downgrade():
    with op.batch_alter_table("sources") as batch_op:
        batch_op.drop_column("http_last_modified")
        batch_op.drop_column("http_etag")
