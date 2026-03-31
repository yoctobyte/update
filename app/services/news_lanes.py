"""News lane service: builds, ranks, and persists Vandaag (today) and Week lanes.

Pipeline per lane:
1. Build candidate pool (public stories + standalone articles)
2. Compute seed score for initial ordering
3. Bounded pairwise heuristic comparison (~6 neighbors per item)
4. Accumulate wins/losses/similars → rank_score
5. Blend rank_score + freshness_score → blend_score
6. Persist results; editorial overrides (pinned/manual) survive recomputes

Ranking is fully heuristic — no LLM involved. The comparator (_compare) scores
each pair on: story bonus, source count, geo scope, uitgelicht worthiness, and
recency. Gap thresholds (0.3 soft / 0.8 strong) determine the outcome.

LLM upgrade path (if ever needed):
  Replace _compare() with an LLM-backed comparator that returns the same dict:
    {"result": "a_higher"|"b_higher"|"similar", "preferred": "a"|"b"|None}
  The rest of the pipeline (neighborhood loop, score accumulation, blend) is
  comparator-agnostic and requires no changes. LLM calls should be bounded
  (only on difficult pairs where |gap| < threshold) and cached to avoid cost.
"""
import logging
import math
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import flask

from ..extensions import db
from ..models.news_lane import NewsLaneItem, LANE_TODAY, LANE_WEEK

logger = logging.getLogger(__name__)

LANE_TODAY_WINDOW_HOURS = 42
LANE_WEEK_WINDOW_DAYS = 12

# Max items stored (and shown) per lane after ranking
_LANE_MAX_ITEMS = {
    LANE_TODAY: 30,
    LANE_WEEK:  20,
}

# (rank_weight, freshness_weight)
_BLEND_WEIGHTS = {
    LANE_TODAY: (0.5, 0.5),
    LANE_WEEK:  (0.7, 0.3),
}

# Freshness half-life in hours
_FRESHNESS_HALFLIFE = {
    LANE_TODAY: 24.0,
    LANE_WEEK:  72.0,
}

# Each item is compared against this many seeded neighbors
_NEIGHBORHOOD = 6

# Higher = more local
_GEO_RANK = {"local": 4, "region": 3, "province": 2, "national": 1, None: 3}

# Gap thresholds for comparator outcome
_GAP_STRONG = 0.8
_GAP_SOFT = 0.3


@dataclass
class LaneCandidate:
    type: str           # 'story' | 'article'
    id: int
    title: str
    latest_date: datetime | None
    source_count: int
    geo_scope: str | None
    uitgelicht_worthy: bool
    is_story: bool
    seed_score: float = 0.0
    wins: int = 0
    losses: int = 0
    similars: int = 0
    preference_wins: int = 0
    preference_losses: int = 0
    comparisons: int = 0
    rank_score: float = 0.0
    freshness_score: float = 0.0
    blend_score: float = 0.0


# ── helpers ───────────────────────────────────────────────────────────────────

def _app_context(app):
    return nullcontext() if flask.has_app_context() else app.app_context()


def _to_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _age_hours(dt: datetime | None) -> float:
    if dt is None:
        return 48.0
    return max(0.0, (datetime.utcnow() - _to_naive(dt)).total_seconds() / 3600.0)


def _freshness(dt: datetime | None, lane: str) -> float:
    half_life = _FRESHNESS_HALFLIFE[lane]
    return math.exp(-math.log(2) * _age_hours(dt) / half_life)


def _seed_score(c: LaneCandidate) -> float:
    score = _GEO_RANK.get(c.geo_scope, 2) * 0.3
    score += min(c.source_count, 5) * 0.4
    score += 0.5 if c.is_story else 0.0
    score += 0.3 if c.uitgelicht_worthy else 0.0
    score += max(0.0, 1.0 - _age_hours(c.latest_date) / 72.0) * 0.3
    return score


def _compare(a: LaneCandidate, b: LaneCandidate) -> dict:
    """Heuristic comparator. Returns {'result': ..., 'preferred': ...}."""
    sa_ = 0.0
    sb_ = 0.0

    if a.is_story and not b.is_story:
        sa_ += 1.5
    elif b.is_story and not a.is_story:
        sb_ += 1.5

    sa_ += min(a.source_count, 5) * 0.4
    sb_ += min(b.source_count, 5) * 0.4

    sa_ += _GEO_RANK.get(a.geo_scope, 2) * 0.3
    sb_ += _GEO_RANK.get(b.geo_scope, 2) * 0.3

    sa_ += 0.3 if a.uitgelicht_worthy else 0.0
    sb_ += 0.3 if b.uitgelicht_worthy else 0.0

    sa_ += max(0.0, 1.0 - _age_hours(a.latest_date) / 72.0) * 0.5
    sb_ += max(0.0, 1.0 - _age_hours(b.latest_date) / 72.0) * 0.5

    gap = sa_ - sb_
    if gap >= _GAP_STRONG:
        return {"result": "a_higher", "preferred": None}
    if gap <= -_GAP_STRONG:
        return {"result": "b_higher", "preferred": None}
    if gap >= _GAP_SOFT:
        return {"result": "similar", "preferred": "a"}
    if gap <= -_GAP_SOFT:
        return {"result": "similar", "preferred": "b"}
    return {"result": "similar", "preferred": None}


# ── candidate pool ────────────────────────────────────────────────────────────

def _story_latest_date(story) -> datetime | None:
    dates = [_to_naive(a.published_at or a.created_at) for a in story.articles
             if a.published_at or a.created_at]
    return max(dates) if dates else None


def _story_source_count(story) -> int:
    return len({a.source_id for a in story.articles})


def _build_candidates(lane: str) -> list[LaneCandidate]:
    from ..models import Article, Story, FrontpageItem

    if lane == LANE_TODAY:
        cutoff = datetime.utcnow() - timedelta(hours=LANE_TODAY_WINDOW_HOURS)
    else:
        cutoff = datetime.utcnow() - timedelta(days=LANE_WEEK_WINDOW_DAYS)

    # --- Story candidates ---
    stories = Story.query.filter(
        Story.status == "active",
        Story.description.isnot(None),
    ).all()

    story_candidates: list[LaneCandidate] = []
    story_article_ids: set[int] = set()

    for story in stories:
        latest = _story_latest_date(story)
        if latest is None or latest < cutoff:
            continue
        for a in story.articles:
            story_article_ids.add(a.id)
        scopes = [a.geo_scope for a in story.articles if a.geo_scope]
        geo = max(scopes, key=lambda s: _GEO_RANK.get(s, 2)) if scopes else None
        uitgelicht_worthy = any(
            a.frontpage_worthy is True or a.geo_scope in (None, "local", "region", "province")
            for a in story.articles
        )
        story_candidates.append(LaneCandidate(
            type="story",
            id=story.id,
            title=story.title,
            latest_date=latest,
            source_count=_story_source_count(story),
            geo_scope=geo,
            uitgelicht_worthy=uitgelicht_worthy,
            is_story=True,
        ))

    # --- Article candidates ---
    fp_ids = {
        row.article_id
        for row in FrontpageItem.query.filter(FrontpageItem.removed_at.is_(None)).all()
    }

    articles = (
        Article.query
        .join(Article.source)
        .filter_by(active=True)
        .filter(Article.summary.isnot(None))
        .filter(
            db.or_(
                Article.published_at >= cutoff,
                db.and_(Article.published_at.is_(None), Article.created_at >= cutoff),
            )
        )
        .filter(
            Article.geo_scope.in_(["local", "region", "province", "national"]) |
            Article.geo_scope.is_(None)
        )
        .order_by(db.func.coalesce(Article.published_at, Article.created_at).desc())
        .all()
    )

    article_candidates: list[LaneCandidate] = []
    for a in articles:
        if a.id in story_article_ids:
            continue
        if any(t.frontpage_rule == "always_out" for t in a.topics):
            continue
        worthy = (
            a.id in fp_ids
            or a.frontpage_worthy is True
            or a.geo_scope in (None, "local", "region", "province")
        )
        if not worthy:
            continue
        pub = _to_naive(a.published_at or a.created_at)
        article_candidates.append(LaneCandidate(
            type="article",
            id=a.id,
            title=a.title,
            latest_date=pub,
            source_count=1,
            geo_scope=a.geo_scope,
            uitgelicht_worthy=a.id in fp_ids or a.frontpage_worthy is True,
            is_story=False,
        ))

    return story_candidates + article_candidates


# ── ranking ───────────────────────────────────────────────────────────────────

def _rank(candidates: list[LaneCandidate], lane: str) -> list[LaneCandidate]:
    if not candidates:
        return candidates

    for c in candidates:
        c.seed_score = _seed_score(c)
    candidates.sort(key=lambda c: c.seed_score, reverse=True)

    n = len(candidates)
    half = _NEIGHBORHOOD // 2
    for i, a in enumerate(candidates):
        start = max(0, i - half)
        neighbors = [candidates[j] for j in range(start, min(n, i + _NEIGHBORHOOD + 1)) if j != i]
        for b in neighbors[:_NEIGHBORHOOD]:
            result = _compare(a, b)
            a.comparisons += 1
            b.comparisons += 1
            r = result["result"]
            if r == "a_higher":
                a.wins += 1
                b.losses += 1
            elif r == "b_higher":
                b.wins += 1
                a.losses += 1
            else:
                a.similars += 1
                b.similars += 1
                pref = result.get("preferred")
                if pref == "a":
                    a.preference_wins += 1
                    b.preference_losses += 1
                elif pref == "b":
                    b.preference_wins += 1
                    a.preference_losses += 1

    max_possible = max(_NEIGHBORHOOD, 1)
    for c in candidates:
        raw = c.wins + 0.3 * c.preference_wins - 0.5 * c.losses - 0.15 * c.preference_losses
        c.rank_score = max(0.0, raw / max_possible)

    for c in candidates:
        c.freshness_score = _freshness(c.latest_date, lane)

    rw, fw = _BLEND_WEIGHTS[lane]
    for c in candidates:
        c.blend_score = rw * c.rank_score + fw * c.freshness_score

    candidates.sort(key=lambda c: c.blend_score, reverse=True)
    return candidates


# ── persistence ───────────────────────────────────────────────────────────────

def _clear_auto_items(lane: str) -> None:
    """Retire auto-computed items for a lane, leaving editorial overrides intact."""
    now = datetime.utcnow()
    auto = NewsLaneItem.query.filter(
        NewsLaneItem.lane == lane,
        NewsLaneItem.removed_at.is_(None),
        NewsLaneItem.pinned.is_(False),
        NewsLaneItem.editorial_note.is_(None),
    ).all()
    for item in auto:
        item.removed_at = now
    if auto:
        db.session.commit()


def _persist_lane(lane: str, ranked: list[LaneCandidate]) -> None:
    now = datetime.utcnow()
    if lane == LANE_TODAY:
        cutoff = now - timedelta(hours=LANE_TODAY_WINDOW_HOURS)
    else:
        cutoff = now - timedelta(days=LANE_WEEK_WINDOW_DAYS)

    _clear_auto_items(lane)

    ranked = ranked[:_LANE_MAX_ITEMS[lane]]
    for c in ranked:
        item = NewsLaneItem(
            lane=lane,
            article_id=c.id if c.type == "article" else None,
            story_id=c.id if c.type == "story" else None,
            window_start=cutoff,
            window_end=now,
            rank_score=round(c.rank_score, 4),
            freshness_score=round(c.freshness_score, 4),
            blend_score=round(c.blend_score, 4),
            wins=c.wins,
            losses=c.losses,
            similars=c.similars,
            preference_wins=c.preference_wins,
            preference_losses=c.preference_losses,
            comparisons=c.comparisons,
            computed_at=now,
        )
        db.session.add(item)
    db.session.commit()


# ── public API ────────────────────────────────────────────────────────────────

def recompute_lane(app_or_none, lane: str) -> int:
    """Rebuild and persist a lane. Returns item count.

    Pass an app object when called outside a request context (e.g. scheduler).
    Pass None when called from within an active app context (e.g. admin view).
    """
    ctx = nullcontext() if flask.has_app_context() else app_or_none.app_context()
    with ctx:
        candidates = _build_candidates(lane)
        if not candidates:
            logger.info("Lane %s: no candidates, clearing", lane)
            _clear_auto_items(lane)
            return 0
        ranked = _rank(candidates, lane)
        _persist_lane(lane, ranked)
        logger.info("Lane %s: persisted %d items", lane, len(ranked))
        return len(ranked)


def get_lane_items(lane: str, limit: int = 100) -> list[NewsLaneItem]:
    """Return active (non-removed, non-suppressed) items, pinned first then by blend_score."""
    return (
        NewsLaneItem.query
        .filter(
            NewsLaneItem.lane == lane,
            NewsLaneItem.removed_at.is_(None),
            NewsLaneItem.suppressed.is_(False),
        )
        .order_by(
            NewsLaneItem.pinned.desc(),
            db.func.coalesce(NewsLaneItem.blend_score, 0.0).desc(),
        )
        .limit(limit)
        .all()
    )
