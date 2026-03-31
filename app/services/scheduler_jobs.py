"""APScheduler job definitions."""
import logging
import traceback
from datetime import datetime
from pathlib import Path

from ..config import Config

logger = logging.getLogger(__name__)

_template_mtimes: dict = {}  # path -> mtime, persists between job runs


def _wrap(job_id, func):
    """Wrap a job function with start/end/error logging."""
    def wrapper(*args, **kwargs):
        logger.info("JOB START  [%s]", job_id)
        t0 = datetime.now()
        try:
            func(*args, **kwargs)
            elapsed = (datetime.now() - t0).total_seconds()
            logger.info("JOB DONE   [%s] in %.1fs", job_id, elapsed)
        except Exception:
            elapsed = (datetime.now() - t0).total_seconds()
            logger.error("JOB ERROR  [%s] after %.1fs\n%s", job_id, elapsed, traceback.format_exc())
    wrapper.__name__ = func.__name__
    return wrapper


def _purge_old_records(app) -> None:
    """Purge personal data past its AVG/GDPR retention period.

    Retention periods are documented in /privacy (privacyverklaring) and must
    stay in sync with that page if changed here.

    ┌─────────────────────────┬──────────────┬──────────────────────────────────────┐
    │ Record type             │ Retention    │ Rationale                            │
    ├─────────────────────────┼──────────────┼──────────────────────────────────────┤
    │ ContactMessage          │ 1 year       │ Sufficient to handle follow-up;      │
    │                         │              │ no legal obligation to keep longer.  │
    ├─────────────────────────┼──────────────┼──────────────────────────────────────┤
    │ Opinion (unpublished /  │ 90 days      │ Short window for editorial review;   │
    │ rejected)               │              │ published opinions are not purged    │
    │                         │              │ here — they are editorial content.   │
    ├─────────────────────────┼──────────────┼──────────────────────────────────────┤
    │ RemovalRequest          │ 2 years      │ Kept longer than others to document  │
    │                         │              │ decisions made (AVG Art. 17(3)       │
    │                         │              │ accountability / legal defence).     │
    └─────────────────────────┴──────────────┴──────────────────────────────────────┘

    Server logs (nginx/gunicorn) are NOT managed here — configure log rotation
    at OS level (logrotate), target 90 days per the privacyverklaring.

    This job runs once per day and is intentionally NOT triggered at startup
    so it does not slow down restarts or interfere with migrations.
    """
    from datetime import timezone, timedelta
    from ..extensions import db
    from ..models import ContactMessage, RemovalRequest
    from ..models.opinion import Opinion

    now = datetime.now(timezone.utc)

    with app.app_context():
        # Contact messages — 1 year
        cutoff_contact = now - timedelta(days=365)
        n = ContactMessage.query.filter(ContactMessage.created_at < cutoff_contact).delete()
        if n:
            logger.info("PURGE: deleted %d contact message(s) older than 1 year", n)

        # Unpublished / rejected opinions — 90 days
        # Published opinions are editorial content and excluded from this purge.
        cutoff_opinion = now - timedelta(days=90)
        n = Opinion.query.filter(
            Opinion.status.in_(["pending", "rejected"]),
            Opinion.created_at < cutoff_opinion,
        ).delete(synchronize_session=False)
        if n:
            logger.info("PURGE: deleted %d unpublished opinion(s) older than 90 days", n)

        # Removal requests — 2 years (accountability retention, AVG Art. 17(3))
        cutoff_removal = now - timedelta(days=730)
        n = RemovalRequest.query.filter(RemovalRequest.created_at < cutoff_removal).delete()
        if n:
            logger.info("PURGE: deleted %d removal request(s) older than 2 years", n)

        db.session.commit()


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


def _describe_pending_stories(app) -> None:
    """Generate descriptions for stories that have 2+ summarized articles but no description yet.

    Acts as a safety net for stories whose articles were not yet summarized when
    clustering ran — the auto_merge trigger fires immediately but articles may
    arrive with a delay on their summaries.
    """
    from ..models import Story
    from .clustering import generate_story_description

    with app.app_context():
        candidates = Story.query.filter(
            Story.description.is_(None),
            Story.status.in_(["suggested", "active"]),
        ).all()

        updated = 0
        for story in candidates:
            summarized = [a for a in story.articles if a.summary]
            if len(summarized) >= 2:
                if generate_story_description(story):
                    updated += 1

        if updated:
            logger.info("DESCRIBE: generated descriptions for %d stories", updated)


def _recompute_vandaag(app) -> None:
    from .news_lanes import recompute_lane
    from ..models.news_lane import LANE_TODAY
    recompute_lane(app, LANE_TODAY)


def _recompute_week(app) -> None:
    from .news_lanes import recompute_lane
    from ..models.news_lane import LANE_WEEK
    recompute_lane(app, LANE_WEEK)


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
        func=_wrap("fetch_all_sources", fetch_all_active),
        args=[app],
        trigger="interval",
        minutes=Config.FETCH_INTERVAL_MINUTES,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="extract_pending",
        func=_wrap("extract_pending", extract_all_pending),
        args=[app],
        trigger="interval",
        minutes=5,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="embed_pending",
        func=_wrap("embed_pending", embed_pending),
        args=[app],
        trigger="interval",
        minutes=Config.EMBED_INTERVAL_MINUTES,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="cluster_stories",
        func=_wrap("cluster_stories", cluster_new_articles),
        args=[app],
        trigger="interval",
        minutes=Config.CLUSTER_INTERVAL_MINUTES,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="fetch_watched_urls",
        func=_wrap("fetch_watched_urls", fetch_all_watched),
        args=[app],
        trigger="interval",
        minutes=30,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="tag_untagged",
        func=_wrap("tag_untagged", tag_untagged_articles),
        args=[app],
        trigger="interval",
        minutes=30,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="refresh_topic_counts",
        func=_wrap("refresh_topic_counts", _refresh_topic_counts),
        args=[app],
        trigger="interval",
        hours=24,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="check_templates",
        func=_wrap("check_templates", _check_templates),
        args=[app],
        trigger="interval",
        seconds=30,
        next_run_time=now,
        replace_existing=True,
    )
    scheduler.add_job(
        id="evaluate_frontpage",
        func=_wrap("evaluate_frontpage", evaluate_pending),
        args=[app],
        trigger="interval",
        minutes=30,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="update_frontpage",
        func=_wrap("update_frontpage", update_frontpage),
        args=[app],
        trigger="interval",
        minutes=30,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="describe_pending_stories",
        func=_wrap("describe_pending_stories", _describe_pending_stories),
        args=[app],
        trigger="interval",
        minutes=30,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="recompute_vandaag",
        func=_wrap("recompute_vandaag", _recompute_vandaag),
        args=[app],
        trigger="interval",
        minutes=30,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="recompute_week",
        func=_wrap("recompute_week", _recompute_week),
        args=[app],
        trigger="interval",
        hours=3,
        next_run_time=now,
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    scheduler.add_job(
        id="purge_old_records",
        func=_wrap("purge_old_records", _purge_old_records),
        args=[app],
        trigger="interval",
        hours=24,
        next_run_time=None,   # don't run on startup, let things settle
        misfire_grace_time=STARTUP_GRACE,
        replace_existing=True,
    )
    logger.info("Scheduler jobs registered: %d jobs", len(scheduler.get_jobs()))
    for job in scheduler.get_jobs():
        logger.info("  %-25s  next: %s", job.id, job.next_run_time)
