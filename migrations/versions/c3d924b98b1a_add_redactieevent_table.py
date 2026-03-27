"""Add RedactieEvent table

Revision ID: c3d924b98b1a
Revises: 0021
Create Date: 2026-03-27 18:27:02.512128

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d924b98b1a'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'redactie_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('location', sa.String(length=300), nullable=True),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('organizer', sa.String(length=200), nullable=True),
        sa.Column('contact_info', sa.String(length=300), nullable=True),
        sa.Column('source_url', sa.String(length=1000), nullable=True),
        sa.Column('published', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('redactie_events') as batch_op:
        batch_op.create_index('ix_redactie_events_start_time', ['start_time'], unique=False)

    op.create_table(
        'redactie_event_topics',
        sa.Column('redactie_event_id', sa.Integer(), nullable=False),
        sa.Column('topic_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['redactie_event_id'], ['redactie_events.id']),
        sa.ForeignKeyConstraint(['topic_id'], ['topics.id']),
        sa.PrimaryKeyConstraint('redactie_event_id', 'topic_id'),
    )
    with op.batch_alter_table('redactie_event_topics') as batch_op:
        batch_op.create_index('ix_redactie_event_topics_topic_id', ['topic_id'], unique=False)


def downgrade():
    with op.batch_alter_table('redactie_event_topics') as batch_op:
        batch_op.drop_index('ix_redactie_event_topics_topic_id')
    op.drop_table('redactie_event_topics')

    with op.batch_alter_table('redactie_events') as batch_op:
        batch_op.drop_index('ix_redactie_events_start_time')
    op.drop_table('redactie_events')
