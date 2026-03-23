"""Add filter_scope to sources and geo_scope to articles.

Replaces the filter_local boolean with a three-way enum:
  "none"   = no filter (all content assumed local)
  "town"   = only keep if primary town name appears
  "region" = keep if town (local) or any region town appears (region)

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    # Add filter_scope to sources
    op.add_column(
        "sources",
        sa.Column("filter_scope", sa.String(10), nullable=False, server_default="none"),
    )
    # Migrate existing filter_local values if that column exists (it may not on fresh DBs)
    conn = op.get_bind()
    cols = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(sources)")).fetchall()]
    if "filter_local" in cols:
        conn.execute(sa.text("UPDATE sources SET filter_scope = 'town' WHERE filter_local = 1"))

    # Add geo_scope to articles
    op.add_column(
        "articles",
        sa.Column("geo_scope", sa.String(10), nullable=True),
    )
    op.create_index("ix_articles_geo_scope", "articles", ["geo_scope"])


def downgrade():
    op.drop_index("ix_articles_geo_scope", table_name="articles")
    op.drop_column("articles", "geo_scope")
    op.drop_column("sources", "filter_scope")
