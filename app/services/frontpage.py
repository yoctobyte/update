"""Frontpage calculation service.

Logic:
- Pool: articles with summary, published within 72h, geo_scope in (local, NULL, region, province, national)
- Per article:
    1. If any topic is always_out → exclude
    2. If any topic is always_in → include
    3. local/region/province (or no geo_scope) → include by default
    4. national → include only if frontpage_worthy=True (call LLM if not yet evaluated)
- Result is written to frontpage_items (new entries added, expired entries stamped with removed_at)
"""
import logging
from contextlib import nullcontext
from datetime import datetime, timedelta

import flask

from ..extensions import db
from ..models import Article, FrontpageItem, SiteSetting


def _app_context(app):
    """Return a context manager that pushes an app context only if needed.
    When called from a view (request context already active), avoids creating
    a nested context that would detach SQLAlchemy objects on exit."""
    return nullcontext() if flask.has_app_context() else app.app_context()

logger = logging.getLogger(__name__)

WINDOW_HOURS = 72


def _get_llm_prompt() -> str | None:
    """Return custom LLM prompt from site_settings, or None to use default."""
    val = SiteSetting.get("frontpage_llm_prompt", "").strip()
    return val if val else None


def _is_worthy(article) -> bool:
    """Determine whether an article belongs on the front page."""
    topics = article.topics

    # always_out overrides everything
    if any(t.frontpage_rule == "always_out" for t in topics):
        return False

    # always_in beats everything else
    if any(t.frontpage_rule == "always_in" for t in topics):
        return True

    # local / region / province (and unclassified) → include by default
    if article.geo_scope in (None, "local", "region", "province"):
        return True

    # national → requires LLM verdict
    if article.geo_scope == "national":
        return article.frontpage_worthy is True

    # intl → never on front page
    return False


def evaluate_pending(app) -> int:
    """Call LLM on national articles in the 72h window that haven't been evaluated yet.
    Returns number of articles evaluated."""
    from .llm import evaluate_frontpage_worthy

    with _app_context(app):
        cutoff = datetime.utcnow() - timedelta(hours=WINDOW_HOURS)
        custom_prompt = _get_llm_prompt()

        pending = (
            Article.query
            .filter(Article.geo_scope == "national")
            .filter(Article.summary.isnot(None))
            .filter(Article.frontpage_worthy.is_(None))
            .filter(Article.published_at >= cutoff)
            .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
            .limit(15)
            .all()
        )

        if not pending:
            return 0

        evaluated = 0
        for article in pending:
            worthy = evaluate_frontpage_worthy(article.title, article.summary or "", custom_prompt)
            if worthy is None:
                continue  # LLM failed, try again next run
            article.frontpage_worthy = worthy
            evaluated += 1

        if evaluated:
            db.session.commit()

        logger.info("Frontpage: evaluated %d national articles", evaluated)
        return evaluated


def update_frontpage(app, dry_run: bool = False) -> list:
    """Rebuild the frontpage. Returns list of Article objects that should be on the front page.

    When dry_run=True: returns the candidate list without touching the DB.
    When dry_run=False: syncs frontpage_items (add new, retire removed).
    """
    with _app_context(app):
        cutoff = datetime.utcnow() - timedelta(hours=WINDOW_HOURS)

        candidates = (
            Article.query
            .join(Article.source)
            .filter_by(active=True)
            .filter(Article.summary.isnot(None))
            .filter(
                db.or_(
                    Article.published_at >= cutoff,
                    Article.published_at.is_(None),  # unclassified date — include conservatively
                )
            )
            .filter(Article.geo_scope.in_(["local", "region", "province", "national"]) |
                    Article.geo_scope.is_(None))
            .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
            .all()
        )

        worthy = [a for a in candidates if _is_worthy(a)]

        if dry_run:
            return worthy

        now = datetime.utcnow()

        # Current active set
        active_items = FrontpageItem.query.filter(FrontpageItem.removed_at.is_(None)).all()
        active_ids = {item.article_id: item for item in active_items}
        worthy_ids = {a.id for a in worthy}

        # Retire articles that dropped off
        for item in active_items:
            if item.article_id not in worthy_ids:
                item.removed_at = now

        # Add newly worthy articles
        for article in worthy:
            if article.id not in active_ids:
                db.session.add(FrontpageItem(article_id=article.id, added_at=now))

        db.session.commit()

        logger.info("Frontpage updated: %d articles (added/retired as needed)", len(worthy))
        return worthy


def get_current_frontpage():
    """Return Article objects currently on the front page, newest first."""
    return (
        Article.query
        .join(FrontpageItem, FrontpageItem.article_id == Article.id)
        .filter(FrontpageItem.removed_at.is_(None))
        .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
        .all()
    )


def frontpage_enabled() -> bool:
    return SiteSetting.get("frontpage_enabled", "0") == "1"
