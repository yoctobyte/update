"""Story clustering: auto-merge or suggest based on embedding similarity."""
import logging
import struct
from datetime import datetime, timezone, timedelta

from ..extensions import db
from ..models import Article, Story, StoryMergeLog, article_stories
from ..config import Config

logger = logging.getLogger(__name__)


def _cosine_to_similarity(distance: float) -> float:
    """sqlite-vec returns cosine distance (0=identical, 2=opposite). Convert to 0-1 similarity."""
    return 1.0 - (distance / 2.0)


def _pack_embedding(raw_bytes: bytes) -> bytes:
    """Re-pack stored float32 bytes as sqlite-vec query format."""
    n = len(raw_bytes) // 4
    floats = struct.unpack(f"{n}f", raw_bytes)
    return struct.pack(f"{n}f", *floats)


def cluster_new_articles(app) -> None:
    """Process articles that have embeddings but no story assignment. Called from scheduler."""
    with app.app_context():
        lookback = datetime.now(timezone.utc) - timedelta(days=Config.CLUSTER_LOOKBACK_DAYS)

        # Articles with embedding but not yet in any story
        assigned_ids = db.session.query(article_stories.c.article_id).subquery()
        candidates = (
            Article.query
            .filter(Article.embedding.isnot(None))
            .filter(Article.created_at >= lookback)
            .filter(~Article.id.in_(assigned_ids))
            .order_by(Article.created_at.asc())
            .all()
        )

        for article in candidates:
            _process_article(article, lookback)


def _process_article(article: Article, lookback: datetime) -> None:
    embedding_bytes = _pack_embedding(article.embedding)

    # KNN query against article_embeddings virtual table, scoped to lookback window
    rows = db.session.execute(
        db.text("""
            SELECT ae.article_id, ae.distance
            FROM article_embeddings ae
            JOIN articles a ON a.id = ae.article_id
            WHERE ae.embedding MATCH :emb
              AND ae.article_id != :aid
              AND a.created_at >= :since
              AND k = 20
            ORDER BY ae.distance
        """),
        {"emb": embedding_bytes, "aid": article.id, "since": lookback},
    ).fetchall()

    if not rows:
        _create_new_story(article)
        return

    # Convert distances to similarities and find the best-matching story
    story_scores: dict[int, list[float]] = {}
    for row in rows:
        sim = _cosine_to_similarity(row.distance)
        neighbor = Article.query.get(row.article_id)
        if not neighbor:
            continue
        for story in neighbor.stories:
            if story.status not in ("active", "suggested"):
                continue
            story_scores.setdefault(story.id, []).append(sim)

    if not story_scores:
        _create_new_story(article)
        return

    # Pick the story with the highest average similarity
    best_story_id = max(story_scores, key=lambda sid: sum(story_scores[sid]) / len(story_scores[sid]))
    best_score = sum(story_scores[best_story_id]) / len(story_scores[best_story_id])
    best_story = Story.query.get(best_story_id)

    if best_score >= Config.STORY_AUTOMERGE_THRESHOLD:
        _auto_merge(article, best_story, best_score)
    elif best_score >= Config.STORY_SUGGEST_THRESHOLD:
        _suggest_merge(article, best_story, best_score)
    else:
        _create_new_story(article)


def _auto_merge(article: Article, story: Story, score: float) -> None:
    article.stories.append(story)
    story.updated_at = datetime.now(timezone.utc)
    log = StoryMergeLog(
        article_id=article.id,
        story_id=story.id,
        similarity_score=score,
        action="auto_merged",
        outcome="merged",
        resolved_by="system",
        resolved_at=datetime.now(timezone.utc),
    )
    db.session.add(log)
    db.session.commit()
    logger.info("Auto-merged article %d into story %d (score %.3f)", article.id, story.id, score)


def _suggest_merge(article: Article, story: Story, score: float) -> None:
    # Only create one pending suggestion per article-story pair
    existing = StoryMergeLog.query.filter_by(
        article_id=article.id, story_id=story.id, outcome="pending"
    ).first()
    if existing:
        return
    log = StoryMergeLog(
        article_id=article.id,
        story_id=story.id,
        similarity_score=score,
        action="suggested",
        outcome="pending",
        resolved_by="system",
    )
    db.session.add(log)
    db.session.commit()
    logger.info("Suggested merge: article %d → story %d (score %.3f)", article.id, story.id, score)


def _create_new_story(article: Article) -> None:
    story = Story(
        title=article.title,
        status="suggested",  # requires editorial promotion before going public
    )
    db.session.add(story)
    db.session.flush()
    article.stories.append(story)
    db.session.commit()
    logger.debug("Created new story %d for article %d", story.id, article.id)


def untie_article_from_story(article_id: int, story_id: int) -> bool:
    """Admin action: remove an article from a story and mark the log as untied."""
    article = Article.query.get(article_id)
    story = Story.query.get(story_id)
    if not article or not story:
        return False

    if story in article.stories:
        article.stories.remove(story)

    log = StoryMergeLog.query.filter_by(
        article_id=article_id, story_id=story_id
    ).order_by(StoryMergeLog.created_at.desc()).first()

    if log:
        log.outcome = "untied"
        log.resolved_by = "admin"
        log.resolved_at = datetime.now(timezone.utc)

    db.session.commit()
    return True
