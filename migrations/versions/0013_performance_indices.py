"""Add performance indices for listing queries.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    # articles.url — critical for _primary_only correlated subquery (dedup)
    # and _sources_by_url batch query. Without this every page load is O(n²).
    op.create_index("ix_articles_url", "articles", ["url"])

    # Composite index for the main listing query filter + sort.
    # Covers: WHERE geo_scope=? AND summary IS NOT NULL ORDER BY published_at DESC
    op.create_index("ix_articles_geo_published", "articles", ["geo_scope", "published_at"])

    # articles.summary — used in IS NOT NULL filters and extract_all_pending
    op.create_index("ix_articles_summary_null", "articles", ["summary"])

    # articles.skip_extraction — extract_all_pending scans this every 5 minutes
    op.create_index("ix_articles_skip_extraction", "articles", ["skip_extraction"])

    # article_topics.topic_id — topic filter does full scan without this
    op.create_index("ix_article_topics_topic_id", "article_topics", ["topic_id"])

    # article_stories.story_id — story lookups benefit from both directions
    op.create_index("ix_article_stories_story_id", "article_stories", ["story_id"])

    # story_topics.topic_id
    op.create_index("ix_story_topics_topic_id", "story_topics", ["topic_id"])

    # event_topics.topic_id — agenda topic filtering
    op.create_index("ix_event_topics_topic_id", "event_topics", ["topic_id"])

    # event_articles.article_id
    op.create_index("ix_event_articles_article_id", "event_articles", ["article_id"])


def downgrade():
    op.drop_index("ix_articles_url", "articles")
    op.drop_index("ix_articles_geo_published", "articles")
    op.drop_index("ix_articles_summary_null", "articles")
    op.drop_index("ix_articles_skip_extraction", "articles")
    op.drop_index("ix_article_topics_topic_id", "article_topics")
    op.drop_index("ix_article_stories_story_id", "article_stories")
    op.drop_index("ix_story_topics_topic_id", "story_topics")
    op.drop_index("ix_event_topics_topic_id", "event_topics")
    op.drop_index("ix_event_articles_article_id", "event_articles")
