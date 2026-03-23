"""Add opinions and contact_messages tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "opinions",
        sa.Column("id",           sa.Integer(),     primary_key=True),
        sa.Column("token",        sa.String(32),    unique=True, nullable=False),
        sa.Column("pen_name",     sa.String(100),   nullable=False),
        sa.Column("title",        sa.String(300),   nullable=False),
        sa.Column("body",         sa.Text(),        nullable=False),
        sa.Column("email",        sa.String(200),   nullable=True),
        sa.Column("status",       sa.String(20),    nullable=False, server_default="pending"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",   sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_opinions_status", "opinions", ["status"])

    op.create_table(
        "contact_messages",
        sa.Column("id",         sa.Integer(),  primary_key=True),
        sa.Column("name",       sa.String(200), nullable=False),
        sa.Column("email",      sa.String(200), nullable=True),
        sa.Column("message",    sa.Text(),      nullable=False),
        sa.Column("read",       sa.Boolean(),   nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("contact_messages")
    op.drop_index("ix_opinions_status", table_name="opinions")
    op.drop_table("opinions")
