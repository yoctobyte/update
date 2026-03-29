"""Add removal_requests table

Revision ID: 4c826e76d443
Revises: c3d924b98b1a
Create Date: 2026-03-29 17:04:31.655937

"""
from alembic import op
import sqlalchemy as sa


revision = '4c826e76d443'
down_revision = 'c3d924b98b1a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('removal_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_type', sa.String(length=20), nullable=False),
        sa.Column('target', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('contact_name', sa.String(length=200), nullable=True),
        sa.Column('email', sa.String(length=200), nullable=True),
        sa.Column('phone', sa.String(length=100), nullable=True),
        sa.Column('phone_app', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('removal_requests')
