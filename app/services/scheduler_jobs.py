"""APScheduler job definitions."""
import logging

from ..config import Config

logger = logging.getLogger(__name__)


def register_jobs(scheduler, app) -> None:
    from .fetcher import fetch_all_active
    from .extractor import extract_all_pending, tag_untagged_articles
    from .embedder import embed_pending
    from .clustering import cluster_new_articles
    from .watcher import fetch_all_watched

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
        replace_existing=True,
    )
    scheduler.add_job(
        id="embed_pending",
        func=embed_pending,
        args=[app],
        trigger="interval",
        minutes=Config.EMBED_INTERVAL_MINUTES,
        replace_existing=True,
    )
    scheduler.add_job(
        id="cluster_stories",
        func=cluster_new_articles,
        args=[app],
        trigger="interval",
        minutes=Config.CLUSTER_INTERVAL_MINUTES,
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
        replace_existing=True,
    )
    scheduler.add_job(
        id="reload_templates",
        func=lambda: app.jinja_env._cache.clear(),
        trigger="interval",
        seconds=30,
        replace_existing=True,
    )
    logger.info("Scheduler jobs registered.")
