"""APScheduler job definitions."""
import logging
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
        app.jinja_env._cache.clear()
        logger.info("Template cache cleared (file change detected)")


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
        id="check_templates",
        func=_check_templates,
        args=[app],
        trigger="interval",
        seconds=30,
        replace_existing=True,
    )
    logger.info("Scheduler jobs registered.")
