"""Add expression index on coalesce(published_at, created_at) and frontpage_worthy index.

The coalesce expression is now the primary sort key for all article listing
queries (articles with no published_at fall back to created_at instead of
sinking to the bottom). Without an expression index SQLite does a full sort
on every page load.

Revision ID: 0020
Revises: 0019
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    # Expression index — covers ORDER BY coalesce(published_at, created_at) DESC
    # used in every listing view and frontpage queries.
    op.execute(
        "CREATE INDEX ix_articles_effective_date "
        "ON articles (coalesce(published_at, created_at) DESC)"
    )

    # Covers evaluate_pending: WHERE geo_scope='national' AND frontpage_worthy IS NULL
    op.execute(
        "CREATE INDEX ix_articles_frontpage_worthy "
        "ON articles (frontpage_worthy)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_articles_effective_date")
    op.execute("DROP INDEX IF EXISTS ix_articles_frontpage_worthy")
