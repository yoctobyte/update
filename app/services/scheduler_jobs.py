"""APScheduler job definitions."""
import logging
from datetime import datetime
from pathlib import Path

from ..config import Config

logger = logging.getLogger(__name__)

_template_mtimes: dict = {}  # path -> mtime, persists between job runs


def _check_templates(app) -> None:
    """Stat template files every 30s. Clear Jinja2 cache only if a file changed."""
    templates_dir = Path(app.root_path) / "templates"
    changed = False

    for path in templates_dir.rglob("*.html"):
        key = str(path)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        prev = _template_mtimes.get(key)
        if prev is None:
            _template_mtimes[key] = mtime          # first run — just record
        elif prev != mtime:
            _template_mtimes[key] = mtime
            changed = True

    if changed:
        app.jinja_env.cache.clear()
        logger.info("Template cache cleared (file change detected)")


def _refresh_topic_counts(app) -> None:
    """Update the cached article_count on every Topic. Run daily."""
    with app.app_context():
        from sqlalchemy import func
        from ..models import Topic
        from ..models.associations import article_topics
        from ..extensions import db

        counts = dict(
            db.session.query(article_topics.c.topic_id, func.count())
            .group_by(article_topics.c.topic_id)
            .all()
        )
        for topic in Topic.query.all():
            topic.article_count = counts.get(topic.id, 0)
        db.session.commit()
        logger.info("Topic article counts refreshed (%d topics with articles)", len(counts))


def register_jobs(scheduler, app) -> None:
    from .fetcher import fetch_all_active
    from .extractor import extract_all_pending, tag_untagged_articles
    from .embedder import embed_pending, preload_model
    from .clustering import cluster_new_articles
    from .watcher import fetch_all_watched
    from .frontpage import evaluate_pending, update_frontpage

    # Pre-warm the embedding model in a background thread so it's ready before
    # the first embed_pending job fires — avoids loading during interpreter shutdown.
    preload_model()

    # Jobs with next_run_time=now run at startup to drain any backlog.
    # misfire_grace_time=60 prevents APScheduler from skipping them when
    # startup takes longer than the default 1-second grace window.
    now = datetime.now()
    STARTUP_GRACE = 60  # seconds

    scheduler.add_job(
        id="fetch_all_sources",
        func=fetch_all_active,
        args=[app],
        trigger="interval",
        minutes=Config.FETCH_INTERVAL_MINUTES,
        replace_existing=True,
    )
    scheduler.add_job(
        id="extract_pending",
        func=extract_all_pending,
        args=[app],
        trigger="interval",
        minutes=5,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="embed_pending",
        func=embed_pending,
        args=[app],
        trigger="interval",
        minutes=Config.EMBED_INTERVAL_MINUTES,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="cluster_stories",
        func=cluster_new_articles,
        args=[app],
        trigger="interval",
        minutes=Config.CLUSTER_INTERVAL_MINUTES,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="fetch_watched_urls",
        func=fetch_all_watched,
        args=[app],
        trigger="interval",
        minutes=30,
        replace_existing=True,
    )
    scheduler.add_job(
        id="tag_untagged",
        func=tag_untagged_articles,
        args=[app],
        trigger="interval",
        minutes=30,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="refresh_topic_counts",
        func=_refresh_topic_counts,
        args=[app],
        trigger="interval",
        hours=24,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="check_templates",
        func=_check_templates,
        args=[app],
        trigger="interval",
        seconds=30,
        next_run_time=now,
        replace_existing=True,
    )
    scheduler.add_job(
        id="evaluate_frontpage",
        func=evaluate_pending,
        args=[app],
        trigger="interval",
        minutes=30,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="update_frontpage",
        func=update_frontpage,
        args=[app],
        trigger="interval",
        minutes=30,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    logger.info("Scheduler jobs registered.")
