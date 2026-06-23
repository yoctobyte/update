"""Add composite indexes for repeated query hotspots.

Revision ID: 0023
Revises: 0022
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    # Public section listings filter by geo_scope and sort by the effective date
    # fallback (published_at or created_at).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_articles_geo_effective_date "
        "ON articles (geo_scope, coalesce(published_at, created_at) DESC)"
    )

    # Extraction queue scans missing summaries while skipping permanently-failed rows.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_articles_extract_queue "
        "ON articles (skip_extraction, summary, id)"
    )

    # Rule lookup is hit on every fetch/extract pass and orders by newest rule first.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_extraction_rules_lookup "
        "ON extraction_rules (source_id, approved, rule_purpose, created_at DESC)"
    )

    # Vandaag/Week public rendering filters active, unsuppressed rows and sorts pinned first.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_news_lane_items_public_order "
        "ON news_lane_items "
        "(lane, removed_at, suppressed, pinned DESC, coalesce(blend_score, 0.0) DESC)"
    )

    # Admin lane view uses the same ordering but includes suppressed rows.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_news_lane_items_admin_order "
        "ON news_lane_items "
        "(lane, removed_at, pinned DESC, coalesce(blend_score, 0.0) DESC)"
    )

    # Story admin/public lookups repeatedly filter by status and often sort by recency.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stories_status_updated_at "
        "ON stories (status, updated_at DESC)"
    )

    # Opinion queues are split by status and sorted by created/published timestamps.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_opinions_status_created_at "
        "ON opinions (status, created_at ASC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_opinions_status_published_at "
        "ON opinions (status, published_at DESC)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_opinions_status_published_at")
    op.execute("DROP INDEX IF EXISTS ix_opinions_status_created_at")
    op.execute("DROP INDEX IF EXISTS ix_stories_status_updated_at")
    op.execute("DROP INDEX IF EXISTS ix_news_lane_items_admin_order")
    op.execute("DROP INDEX IF EXISTS ix_news_lane_items_public_order")
    op.execute("DROP INDEX IF EXISTS ix_extraction_rules_lookup")
    op.execute("DROP INDEX IF EXISTS ix_articles_extract_queue")
    op.execute("DROP INDEX IF EXISTS ix_articles_geo_effective_date")
