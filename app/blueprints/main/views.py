import json
import re
import unicodedata
from flask import render_template, request, abort, redirect, url_for, flash, current_app, send_file, Response
from . import bp
from ...models import Article, Story, Event, RedactieEvent, Topic, Opinion, ContactMessage, Source, RedactionalPost
from ...extensions import db, limiter
from ...config import Config


def slugify(text: str) -> str:
    """Return a URL-safe slug derived from text."""
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "artikel"


# ── helpers ───────────────────────────────────────────────────────────────────

def _town_cfg() -> dict:
    try:
        return json.loads(Config.town_config_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


_SECTION_FLAG = {
    "local":    "show_local",
    "region":   "show_region",
    "province": "show_province",
    "national": "show_national",
    "intl":     "show_intl",
    "alles":    "show_alles",
}


TOPIC_SIDEBAR_TOP = 7

_PIN_SECTION = {
    "local":     "pin_lokaal",
    "region":    "pin_regio",
    "province":  "pin_provincie",
    "national":  "pin_nationaal",
    "intl":      "pin_intl",
    "alles":     "pin_alles",
    "frontpage": "pin_frontpage",
}


def _mix_stories(articles) -> list:
    """Replace articles that belong to an active story (with description) with a story card.

    The first article encountered from each active story is replaced by the story
    object (marked with is_story_card=True). Subsequent articles from the same
    story are suppressed — they are already represented by the card.
    Articles not in any active story pass through unchanged.
    RedactionalPost items (is_redactional_post=True) are never touched.
    """
    from ...models.associations import article_stories as _at

    plain = [a for a in articles if not getattr(a, 'is_redactional_post', False)]
    if not plain:
        return list(articles)

    article_ids = [a.id for a in plain]
    memberships = db.session.execute(
        _at.select().where(_at.c.article_id.in_(article_ids))
    ).fetchall()
    if not memberships:
        return list(articles)

    story_ids = list({row.story_id for row in memberships})
    article_to_story = {row.article_id: row.story_id for row in memberships}

    active_stories = {
        s.id: s for s in Story.query.filter(
            Story.id.in_(story_ids),
            Story.description.isnot(None),
            Story.status == "active",
        ).all()
    }
    if not active_stories:
        return list(articles)

    # Pre-compute display date and sources for each story card
    for story in active_stories.values():
        dates = [a.published_at or a.created_at for a in story.articles if a.published_at or a.created_at]
        story._display_date = max(dates) if dates else story.created_at
        story.is_story_card = True

    result = []
    seen_story_ids: set = set()
    for item in articles:
        if getattr(item, 'is_redactional_post', False):
            result.append(item)
            continue
        story_id = article_to_story.get(item.id)
        if story_id and story_id in active_stories:
            if story_id not in seen_story_ids:
                result.append(active_stories[story_id])
                seen_story_ids.add(story_id)
            # else: suppress — story card already emitted
        else:
            result.append(item)
    return result


def _inject_pins(articles, section: str, page: int) -> list:
    """Insert active pinned RedactionalPosts into article list (page 1 only).

    Posts are inserted at their pin_position (0-indexed). Multiple posts at the
    same position stack in published_at order; each insertion shifts subsequent
    positions by one.
    """
    from datetime import datetime, timezone

    if page != 1:
        return list(articles)

    flag = _PIN_SECTION.get(section)
    if not flag:
        return list(articles)

    now = datetime.now(timezone.utc)
    pins = (
        RedactionalPost.query
        .filter(
            getattr(RedactionalPost, flag) == True,
            RedactionalPost.pinned == True,
            RedactionalPost.visible == True,
            db.or_(
                RedactionalPost.pin_expires_at.is_(None),
                RedactionalPost.pin_expires_at > now,
            ),
        )
        .order_by(RedactionalPost.pin_position, RedactionalPost.published_at.desc())
        .all()
    )

    if not pins:
        return list(articles)

    result = list(articles)
    offset = 0
    for post in pins:
        pos = min((post.pin_position or 0) + offset, len(result))
        result.insert(pos, post)
        offset += 1
    return result


def _topic_groups(section: str, active_topic=None):
    """Return (topics_top, topics_section, topics_all) for the sidebar.

    topics_top:     up to TOPIC_SIDEBAR_TOP most-populated section-visible topics
                    (always shown); active_topic appended if not already included
    topics_section: remaining section-visible topics (hidden, first "..." press)
    topics_all:     topics not visible in this section (hidden, second "..." press)
    """
    flag = _SECTION_FLAG.get(section)
    all_topics = Topic.query.order_by(Topic.article_count.desc(), Topic.name).all()

    section_visible = [t for t in all_topics if flag is None or getattr(t, flag)]
    not_section     = [t for t in all_topics if flag is not None and not getattr(t, flag)]

    top           = section_visible[:TOPIC_SIDEBAR_TOP]
    section_rest  = section_visible[TOPIC_SIDEBAR_TOP:]

    # Surface active_topic if it's buried in overflow
    if active_topic:
        top_ids = {t.id for t in top}
        if active_topic.id not in top_ids:
            section_rest = [t for t in section_rest if t.id != active_topic.id]
            not_section  = [t for t in not_section  if t.id != active_topic.id]
            top.append(active_topic)

    return top, section_rest, not_section


def _primary_only(query):
    """Exclude URL duplicates: keep only the first-fetched article per URL.
    When the same URL is picked up by multiple sources, only the lowest-id
    copy appears in listings; the others are still reachable via direct link."""
    duplicate = db.aliased(Article)
    return query.filter(
        ~db.session.query(duplicate)
        .filter(duplicate.url == Article.url, duplicate.id < Article.id)
        .exists()
    )


def _sources_by_url(articles) -> dict:
    """Batch-query all active sources covering each URL on the page.

    Two passes:
    1. Exact URL match — catches the same article fetched by multiple RSS feeds.
    2. Story siblings — when articles about the same story (different URLs,
       different publishers) are merged, all their sources appear under each card.

    Returns dict[url -> list[Source]].
    """
    from collections import defaultdict
    from ...models.associations import article_stories as _at

    urls = list({a.url for a in articles if a.url})
    if not urls:
        return {}

    # Pass 1: exact URL match
    rows = (
        db.session.query(Article.url, Source)
        .join(Article.source)
        .filter(Article.url.in_(urls))
        .filter(Source.active == True)
        .all()
    )
    result: dict = defaultdict(list)
    seen: dict = defaultdict(set)  # url -> set of source_ids already added
    for url, source in rows:
        if source.id not in seen[url]:
            seen[url].add(source.id)
            result[url].append(source)

    # Pass 2: story siblings — different URLs, same story
    article_ids = [a.id for a in articles]
    url_by_id = {a.id: a.url for a in articles}

    memberships = db.session.execute(
        _at.select().where(_at.c.article_id.in_(article_ids))
    ).fetchall()
    if not memberships:
        return dict(result)

    story_ids = list({row.story_id for row in memberships})
    # article_id -> set of story_ids it belongs to
    art_stories: dict = defaultdict(set)
    for row in memberships:
        art_stories[row.article_id].add(row.story_id)

    # All (story_id, sibling_url, sibling_source) in those stories
    sibling_rows = (
        db.session.query(_at.c.story_id, Article.url, Source)
        .join(Article, Article.id == _at.c.article_id)
        .join(Source, Source.id == Article.source_id)
        .filter(_at.c.story_id.in_(story_ids))
        .filter(Source.active == True)
        .all()
    )
    # story_id -> list of (url, source) for all members
    story_sources: dict = defaultdict(list)
    seen_story: dict = defaultdict(set)
    for story_id, sib_url, sib_source in sibling_rows:
        if sib_source.id not in seen_story[story_id]:
            seen_story[story_id].add(sib_source.id)
            story_sources[story_id].append((sib_url, sib_source))

    # For each displayed article, merge in sources from its story siblings
    for article in articles:
        if not article.url:
            continue
        for story_id in art_stories.get(article.id, set()):
            for sib_url, sib_source in story_sources[story_id]:
                if sib_url != article.url and sib_source.id not in seen[article.url]:
                    seen[article.url].add(sib_source.id)
                    result[article.url].append(sib_source)

    return dict(result)


# ── News ──────────────────────────────────────────────────────────────────────

def _lokaal_response():
    """Render the local news listing. Used by both / (fallback) and /<town_slug>."""
    page = request.args.get("page", 1, type=int)
    topic_id = request.args.get("topic", type=int)

    query = (
        Article.query
        .join(Article.source)
        .filter_by(active=True)
        .filter(Article.geo_scope == "local")
        .filter(Article.summary.isnot(None))
        .order_by(db.func.coalesce(Article.published_at, Article.created_at).desc())
    )
    if topic_id:
        query = query.filter(Article.topics.any(id=topic_id))

    pagination = _primary_only(query).paginate(page=page, per_page=min(request.args.get("per_page", 100, type=int), 200), error_out=False)
    active_topic = Topic.query.get(topic_id) if topic_id else None
    topics_top, topics_section, topics_all = _topic_groups("local", active_topic)

    return render_template(
        "main/index.html",
        pagination=pagination,
        topics_top=topics_top,
        topics_section=topics_section,
        topics_all=topics_all,
        active_topic=active_topic,
        section_endpoint="main.lokaal",
        sources_by_url=_sources_by_url(pagination.items),
        page_items=_inject_pins(_mix_stories(pagination.items), "local", page),
    )


def lokaal():
    """Canonical local news view — registered at /<town_slug> by create_app."""
    return _lokaal_response()


@bp.route("/lokaal")
def lokaal_redirect():
    """Backward-compat alias: redirect to the canonical /<town_slug> URL."""
    town = current_app.jinja_env.globals.get("site_town", "").lower()
    if town:
        params = {k: v for k, v in request.args.items() if k in ("topic_id", "page", "per_page")}
        return redirect(url_for("main.lokaal", **params), 301)
    return _lokaal_response()


@bp.route("/")
def index():
    """Root: dispatch to the configured main public view."""
    from ...services.frontpage import (
        HOMEPAGE_VIEW_UITGELICHT,
        HOMEPAGE_VIEW_VANDAAG,
        HOMEPAGE_VIEW_WEEK,
        get_homepage_view,
    )
    view = get_homepage_view()
    if view == HOMEPAGE_VIEW_UITGELICHT:
        return _uitgelicht_response()
    if view == HOMEPAGE_VIEW_VANDAAG:
        return _vandaag_response()
    if view == HOMEPAGE_VIEW_WEEK:
        return _week_response()
    return _lokaal_response()


def _uitgelicht_response():
    """Render the current Uitgelicht lane."""
    from ...services.frontpage import get_current_frontpage

    articles = get_current_frontpage()
    topics = Topic.query.order_by(Topic.name).all()
    return render_template(
        "main/frontpage.html",
        articles=articles,
        topics=topics,
        sources_by_url=_sources_by_url(articles),
        page_items=_inject_pins(_mix_stories(articles), "frontpage", 1),
    )


def _resolve_lane_items(lane_items):
    """Convert NewsLaneItem list to a renderable list (Articles/Stories).

    Pinned items may be editorial (no computed_at). We render them regardless.
    Story items get _display_date and is_story_card injected so _story_card.html works.
    """
    result = []
    for item in lane_items:
        if item.story_id and item.story:
            story = item.story
            if not hasattr(story, "_display_date"):
                dates = [a.published_at or a.created_at for a in story.articles
                         if a.published_at or a.created_at]
                story._display_date = max(dates) if dates else story.created_at
            story.is_story_card = True
            result.append(story)
        elif item.article_id and item.article:
            result.append(item.article)
    return result


def _vandaag_response():
    from ...services.news_lanes import get_lane_items, LANE_TODAY
    items = get_lane_items(LANE_TODAY)
    rendered = _resolve_lane_items(items)
    articles = [r for r in rendered if not getattr(r, "is_story_card", False)]
    return render_template(
        "main/vandaag.html",
        page_items=rendered,
        sources_by_url=_sources_by_url(articles),
    )


def _week_response():
    from ...services.news_lanes import get_lane_items, LANE_WEEK
    items = get_lane_items(LANE_WEEK)
    rendered = _resolve_lane_items(items)
    articles = [r for r in rendered if not getattr(r, "is_story_card", False)]
    return render_template(
        "main/week.html",
        page_items=rendered,
        sources_by_url=_sources_by_url(articles),
    )


@bp.route("/uitgelicht")
def uitgelicht():
    """Stable route for the curated main lane."""
    return _uitgelicht_response()


@bp.route("/vandaag")
def vandaag():
    """Stable route for the Vandaag lane (last ~42 hours)."""
    return _vandaag_response()


@bp.route("/week")
def week():
    """Stable route for the Week lane (last ~12 days)."""
    return _week_response()


@bp.route("/nieuws/<int:article_id>")
def article_detail_redirect(article_id):
    article = Article.query.filter_by(id=article_id).first_or_404()
    return redirect(
        url_for("main.article_detail", article_id=article_id, slug=slugify(article.title or "")),
        301,
    )


@bp.route("/nieuws/<int:article_id>/<slug>")
def article_detail(article_id, slug):
    article = Article.query.filter_by(id=article_id).first()
    if article is None:
        from ...services.clustering import search_by_text
        query = slug.replace("-", " ")
        results = search_by_text(query, limit=5)
        sources_by_url = _sources_by_url([a for a, _ in results])
        return render_template(
            "main/article_404.html",
            query=query,
            results=results,
            sources_by_url=sources_by_url,
        ), 404
    if article.summary is None:
        from ...services.clustering import search_by_text
        query = (article.title or slug.replace("-", " "))
        results = search_by_text(query, limit=25)
        sources_by_url = _sources_by_url([a for a, _ in results])
        return render_template(
            "main/article_202.html",
            article=article,
            query=query,
            results=results,
            sources_by_url=sources_by_url,
        ), 202

    # Other fetched copies of the same URL (from different sources)
    same_url_others = Article.query.filter(
        Article.url == article.url,
        Article.id != article.id
    ).all()

    # Related articles via shared stories (exclude this article and same-URL copies)
    related_per_story = {}  # story -> [articles]
    seen_ids = {article.id} | {a.id for a in same_url_others}
    for story in article.stories:
        if story.status != "active":
            continue
        others = [a for a in story.articles if a.id not in seen_ids]
        if others:
            related_per_story[story] = others

    # Merge log entries for this article
    from ...models import StoryMergeLog
    merge_logs = article.merge_logs.order_by(StoryMergeLog.created_at.desc()).all()

    # Vector similarity: 20 most related articles (wider pool for story discovery)
    # Exclude story siblings (already in "Gerelateerde verhalen") and same-URL copies
    from ...services.clustering import find_similar_articles
    sibling_ids = {a.id for articles in related_per_story.values() for a in articles}
    sibling_ids |= {a.id for a in same_url_others}
    similar_articles_raw = find_similar_articles(article, limit=20, exclude_ids=sibling_ids)

    # Related stories found via similar articles (not stories this article already belongs to)
    seen_story_ids = {s.id for s in article.stories}
    similar_stories = []
    similar_story_article_ids = set()
    for sim_article, _ in similar_articles_raw:
        for s in sim_article.stories:
            if s.status == "active" and s.id not in seen_story_ids:
                seen_story_ids.add(s.id)
                story_arts = [a for a in s.articles if a.summary]
                if story_arts:
                    similar_stories.append((s, story_arts))
                    similar_story_article_ids.update(a.id for a in story_arts)

    # Only show similar articles not already surfaced via a related story
    similar_articles = [
        (a, score) for a, score in similar_articles_raw
        if a.id not in similar_story_article_ids
    ][:8]

    return render_template(
        "main/article_detail.html",
        article=article,
        same_url_others=same_url_others,
        related_per_story=related_per_story,
        merge_logs=merge_logs,
        similar_articles=similar_articles,
        similar_stories=similar_stories,
    )


# ── Regio ─────────────────────────────────────────────────────────────────────

@bp.route("/regio")
def regio():
    page = request.args.get("page", 1, type=int)
    topic_id = request.args.get("topic", type=int)

    cfg = _town_cfg()
    region_towns = cfg.get("region_towns", [])

    query = (
        Article.query
        .join(Article.source)
        .filter_by(active=True)
        .filter(Article.geo_scope == "region")
        # Only publish once the AI rewrite is done
        .filter(Article.summary.isnot(None))
        .order_by(db.func.coalesce(Article.published_at, Article.created_at).desc())
    )
    if topic_id:
        query = query.filter(Article.topics.any(id=topic_id))

    pagination = _primary_only(query).paginate(page=page, per_page=min(request.args.get("per_page", 100, type=int), 200), error_out=False)
    active_topic = Topic.query.get(topic_id) if topic_id else None
    topics_top, topics_section, topics_all = _topic_groups("region", active_topic)

    return render_template(
        "main/regio.html",
        pagination=pagination,
        topics_top=topics_top,
        topics_section=topics_section,
        topics_all=topics_all,
        active_topic=active_topic,
        section_endpoint="main.regio",
        region_towns=region_towns,
        sources_by_url=_sources_by_url(pagination.items),
        page_items=_inject_pins(_mix_stories(pagination.items), "region", page),
    )


# ── Provincie ─────────────────────────────────────────────────────────────────

@bp.route("/provincie")
def provincie():
    page = request.args.get("page", 1, type=int)
    topic_id = request.args.get("topic", type=int)

    query = (
        Article.query
        .join(Article.source)
        .filter_by(active=True)
        .filter(Article.geo_scope == "province")
        .filter(Article.summary.isnot(None))
        .order_by(db.func.coalesce(Article.published_at, Article.created_at).desc())
    )
    if topic_id:
        query = query.filter(Article.topics.any(id=topic_id))

    pagination = _primary_only(query).paginate(page=page, per_page=min(request.args.get("per_page", 100, type=int), 200), error_out=False)
    active_topic = Topic.query.get(topic_id) if topic_id else None
    topics_top, topics_section, topics_all = _topic_groups("province", active_topic)

    return render_template(
        "main/provincie.html",
        pagination=pagination,
        topics_top=topics_top,
        topics_section=topics_section,
        topics_all=topics_all,
        active_topic=active_topic,
        section_endpoint="main.provincie",
        sources_by_url=_sources_by_url(pagination.items),
        page_items=_inject_pins(_mix_stories(pagination.items), "province", page),
    )


# ── Nationaal ─────────────────────────────────────────────────────────────────

@bp.route("/nationaal")
def nationaal():
    page = request.args.get("page", 1, type=int)
    topic_id = request.args.get("topic", type=int)

    query = (
        Article.query
        .join(Article.source)
        .filter_by(active=True)
        .filter(Article.geo_scope == "national")
        .filter(Article.summary.isnot(None))
        .order_by(db.func.coalesce(Article.published_at, Article.created_at).desc())
    )
    if topic_id:
        query = query.filter(Article.topics.any(id=topic_id))

    pagination = _primary_only(query).paginate(page=page, per_page=min(request.args.get("per_page", 100, type=int), 200), error_out=False)
    active_topic = Topic.query.get(topic_id) if topic_id else None
    topics_top, topics_section, topics_all = _topic_groups("national", active_topic)

    return render_template(
        "main/nationaal.html",
        pagination=pagination,
        topics_top=topics_top,
        topics_section=topics_section,
        topics_all=topics_all,
        active_topic=active_topic,
        section_endpoint="main.nationaal",
        sources_by_url=_sources_by_url(pagination.items),
        page_items=_inject_pins(_mix_stories(pagination.items), "national", page),
    )


# ── Internationaal ────────────────────────────────────────────────────────────

@bp.route("/internationaal")
def internationaal():
    page = request.args.get("page", 1, type=int)
    topic_id = request.args.get("topic", type=int)

    query = (
        Article.query
        .join(Article.source)
        .filter_by(active=True)
        .filter(Article.geo_scope == "intl")
        .filter(Article.summary.isnot(None))
        .order_by(db.func.coalesce(Article.published_at, Article.created_at).desc())
    )
    if topic_id:
        query = query.filter(Article.topics.any(id=topic_id))

    pagination = _primary_only(query).paginate(page=page, per_page=min(request.args.get("per_page", 100, type=int), 200), error_out=False)
    active_topic = Topic.query.get(topic_id) if topic_id else None
    topics_top, topics_section, topics_all = _topic_groups("intl", active_topic)

    return render_template(
        "main/internationaal.html",
        pagination=pagination,
        topics_top=topics_top,
        topics_section=topics_section,
        topics_all=topics_all,
        active_topic=active_topic,
        section_endpoint="main.internationaal",
        sources_by_url=_sources_by_url(pagination.items),
        page_items=_inject_pins(_mix_stories(pagination.items), "intl", page),
    )


# ── Alles ─────────────────────────────────────────────────────────────────────

@bp.route("/alles")
def alles():
    page = request.args.get("page", 1, type=int)
    topic_id = request.args.get("topic", type=int)

    query = (
        Article.query
        .join(Article.source)
        .filter_by(active=True)
        .filter(Article.summary.isnot(None))
        .order_by(db.func.coalesce(Article.published_at, Article.created_at).desc())
    )
    if topic_id:
        query = query.filter(Article.topics.any(id=topic_id))

    pagination = _primary_only(query).paginate(page=page, per_page=min(request.args.get("per_page", 100, type=int), 200), error_out=False)
    active_topic = Topic.query.get(topic_id) if topic_id else None
    topics_top, topics_section, topics_all = _topic_groups("alles", active_topic)

    return render_template(
        "main/alles.html",
        pagination=pagination,
        topics_top=topics_top,
        topics_section=topics_section,
        topics_all=topics_all,
        active_topic=active_topic,
        section_endpoint="main.alles",
        sources_by_url=_sources_by_url(pagination.items),
        page_items=_inject_pins(_mix_stories(pagination.items), "alles", page),
    )


# ── Redactie — editorial posts ────────────────────────────────────────────────

@bp.route("/redactie")
def redactie():
    page = request.args.get("page", 1, type=int)
    pagination = (
        RedactionalPost.query
        .filter_by(hide=False)
        .order_by(RedactionalPost.published_at.desc())
        .paginate(page=page, per_page=25, error_out=False)
    )
    return render_template("main/redactie.html", pagination=pagination)


@bp.route("/redactie/<int:post_id>")
def redactie_post_redirect(post_id):
    post = RedactionalPost.query.get_or_404(post_id)
    return redirect(
        url_for("main.redactie_post", post_id=post_id, slug=slugify(post.title or "")),
        301,
    )


@bp.route("/redactie/<int:post_id>/<slug>")
def redactie_post(post_id, slug):
    post = RedactionalPost.query.get_or_404(post_id)
    if post.hide:
        abort(404)
    return render_template("main/redactie_post.html", post=post)


# ── Stories ───────────────────────────────────────────────────────────────────

@bp.route("/redactie/verhaal/<int:story_id>")
@bp.route("/redactie/verhaal/<int:story_id>/<slug>")
def redactie_detail(story_id, slug=None):
    story = Story.query.get_or_404(story_id)
    articles = sorted(
        [a for a in story.articles if a.summary],
        key=lambda a: a.published_at or a.created_at,
        reverse=True,
    )
    sources_by_url = _sources_by_url(articles)

    # Related stories and similar articles — use the most recent article as proxy
    related_stories = []
    similar_articles = []
    if articles:
        from ...services.clustering import find_similar_articles
        member_ids = {a.id for a in story.articles}
        similar_raw = find_similar_articles(articles[0], limit=20, exclude_ids=member_ids)

        # Collect related stories from similar articles (excluding this story)
        seen_story_ids = {story.id}
        seen_article_ids = set()
        for sim_article, _ in similar_raw:
            for s in sim_article.stories:
                if s.status == "active" and s.id not in seen_story_ids:
                    seen_story_ids.add(s.id)
                    story_arts = [a for a in s.articles if a.summary]
                    if story_arts:
                        related_stories.append((s, story_arts))

        # Similar articles not belonging to any related story
        related_story_article_ids = {a.id for _, arts in related_stories for a in arts}
        for sim_article, score in similar_raw:
            if sim_article.id not in related_story_article_ids:
                similar_articles.append((sim_article, score))
        similar_articles = similar_articles[:8]

    return render_template(
        "main/story_detail.html",
        story=story,
        articles=articles,
        sources_by_url=sources_by_url,
        related_stories=related_stories,
        similar_articles=similar_articles,
    )


@bp.route("/verhalen")
def verhalen_redirect():
    return redirect(url_for("main.redactie"), 301)


@bp.route("/verhalen/<int:story_id>")
def verhalen_detail_redirect(story_id):
    return redirect(url_for("main.redactie_detail", story_id=story_id), 301)


# ── Events ────────────────────────────────────────────────────────────────────

class _SimplePagination:
    """Minimal pagination object for manually merged querysets."""
    def __init__(self, items, page, per_page, total):
        self.items    = items
        self.page     = page
        self.per_page = per_page
        self.total    = total
        self.pages    = max(1, (total + per_page - 1) // per_page)
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = page - 1
        self.next_num = page + 1


@bp.route("/agenda")
def events():
    from datetime import datetime
    page     = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 100, type=int), 200)
    topic_id = request.args.get("topic", type=int)
    now      = datetime.utcnow()

    scraped_q  = Event.query.filter(Event.start_time >= now)
    redactie_q = RedactieEvent.query.filter(
        RedactieEvent.published == True,
        RedactieEvent.start_time >= now,
    )
    if topic_id:
        scraped_q  = scraped_q.filter(Event.topics.any(id=topic_id))
        redactie_q = redactie_q.filter(RedactieEvent.topics.any(id=topic_id))

    all_events = sorted(scraped_q.all() + redactie_q.all(), key=lambda e: e.start_time)

    offset     = (page - 1) * per_page
    pagination = _SimplePagination(all_events[offset:offset + per_page], page, per_page, len(all_events))

    active_topic = db.session.get(Topic, topic_id) if topic_id else None
    topics_top, topics_section, topics_all = _topic_groups("alles", active_topic)

    return render_template(
        "main/events.html",
        pagination=pagination,
        topics=topics_top + topics_section + topics_all,
        active_topic=active_topic,
    )


@bp.route("/agenda/<int:event_id>")
def event_detail_redirect(event_id):
    event = Event.query.get_or_404(event_id)
    return redirect(
        url_for("main.event_detail", event_id=event_id, slug=slugify(event.title or "")),
        301,
    )


@bp.route("/agenda/<int:event_id>/<slug>")
def event_detail(event_id, slug):
    event = Event.query.get_or_404(event_id)
    return render_template("main/event_detail.html", event=event)


@bp.route("/agenda/redactie/<int:event_id>")
def redactie_event_detail_redirect(event_id):
    event = db.session.get(RedactieEvent, event_id)
    if not event:
        abort(404)
    return redirect(
        url_for("main.redactie_event_detail", event_id=event_id, slug=slugify(event.title or "")),
        301,
    )


@bp.route("/agenda/redactie/<int:event_id>/<slug>")
def redactie_event_detail(event_id, slug):
    event = db.session.get(RedactieEvent, event_id)
    if not event or not event.published:
        abort(404)
    return render_template("main/event_detail.html", event=event)


# ── Ingezonden (was: Opinie) ───────────────────────────────────────────────────

@bp.route("/ingezonden")
def ingezonden_list():
    page = request.args.get("page", 1, type=int)
    pagination = (
        Opinion.query
        .filter_by(status="published")
        .order_by(Opinion.published_at.desc())
        .paginate(page=page, per_page=min(request.args.get("per_page", 100, type=int), 200), error_out=False)
    )
    return render_template("main/opinie_list.html", pagination=pagination)


@bp.route("/ingezonden/<int:opinion_id>")
def ingezonden_detail(opinion_id):
    opinion = Opinion.query.filter_by(id=opinion_id, status="published").first_or_404()
    return render_template("main/opinie_detail.html", opinion=opinion)


@bp.route("/ingezonden/insturen", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def ingezonden_insturen():
    if request.method == "POST":
        pen_name = request.form.get("pen_name", "").strip()
        title    = request.form.get("title", "").strip()
        body     = request.form.get("body", "").strip()
        email    = request.form.get("email", "").strip() or None

        errors = []
        if not pen_name: errors.append("Schuilnaam is verplicht.")
        if not title:    errors.append("Titel is verplicht.")
        if len(body) < 100: errors.append("Tekst moet minimaal 100 tekens bevatten.")

        if errors:
            return render_template("main/opinie_form.html", errors=errors,
                                   pen_name=pen_name, title=title, body=body, email=email)

        opinion = Opinion(pen_name=pen_name, title=title, body=body, email=email)
        db.session.add(opinion)
        db.session.commit()

        edit_url = url_for("main.ingezonden_bewerken", token=opinion.token, _external=True)
        return render_template("main/opinie_ingezonden.html", opinion=opinion, edit_url=edit_url)

    return render_template("main/opinie_form.html", errors=[], pen_name="", title="", body="", email="")


@bp.route("/ingezonden/bewerken/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute; 30 per hour", methods=["POST"])
def ingezonden_bewerken(token):
    opinion = Opinion.query.filter_by(token=token).first_or_404()

    if not opinion.editable:
        return render_template("main/opinie_gesloten.html", opinion=opinion)

    if request.method == "POST":
        pen_name = request.form.get("pen_name", "").strip()
        title    = request.form.get("title", "").strip()
        body     = request.form.get("body", "").strip()

        errors = []
        if not pen_name: errors.append("Schuilnaam is verplicht.")
        if not title:    errors.append("Titel is verplicht.")
        if len(body) < 100: errors.append("Tekst moet minimaal 100 tekens bevatten.")

        if errors:
            return render_template("main/opinie_bewerken.html", opinion=opinion, errors=errors,
                                   pen_name=pen_name, title=title, body=body)

        opinion.pen_name = pen_name
        opinion.title    = title
        opinion.body     = body
        db.session.commit()
        flash("Wijzigingen opgeslagen.", "success")
        return redirect(url_for("main.ingezonden_bewerken", token=token))

    return render_template("main/opinie_bewerken.html", opinion=opinion, errors=[],
                           pen_name=opinion.pen_name, title=opinion.title, body=opinion.body)


@bp.route("/opinie")
def opinie_redirect():
    return redirect(url_for("main.ingezonden_list"), 301)


@bp.route("/opinie/<int:opinion_id>")
def opinie_detail_redirect(opinion_id):
    return redirect(url_for("main.ingezonden_detail", opinion_id=opinion_id), 301)


@bp.route("/opinie/insturen")
def opinie_insturen_redirect():
    return redirect(url_for("main.ingezonden_insturen"), 301)


@bp.route("/opinie/bewerken/<token>")
def opinie_bewerken_redirect(token):
    return redirect(url_for("main.ingezonden_bewerken", token=token), 301)


# ── Search / Zoeken ───────────────────────────────────────────────────────────

@bp.route("/zoeken")
def zoeken():
    query = request.args.get("q", "").strip()
    results = []
    sources_by_url = {}
    if query:
        from ...services.clustering import search_by_text
        articles_and_scores = search_by_text(query, limit=50)
        results = articles_and_scores
        sources_by_url = _sources_by_url([a for a, _ in articles_and_scores])
    return render_template(
        "main/zoeken.html",
        query=query,
        results=results,
        sources_by_url=sources_by_url,
    )


# ── About / Over ons ──────────────────────────────────────────────────────────

@bp.route("/privacy")
def privacy():
    cfg = _town_cfg()
    return render_template("main/privacy.html", contact=cfg.get("contact", {}))


@bp.route("/over-ons")
def about():
    cfg = _town_cfg()
    return render_template(
        "main/about.html",
        contact=cfg.get("contact", {}),
        sponsors=cfg.get("sponsors", []),
    )


@bp.route("/over-ons/contact", methods=["POST"])
@limiter.limit("5 per minute; 10 per hour")
def contact_submit():
    name    = request.form.get("name", "").strip()
    email   = request.form.get("email", "").strip() or None
    message = request.form.get("message", "").strip()

    errors = []
    if not name:    errors.append("Naam is verplicht.")
    if not message: errors.append("Bericht is verplicht.")

    if errors:
        cfg = _town_cfg()
        return render_template("main/about.html",
                               contact=cfg.get("contact", {}),
                               sponsors=cfg.get("sponsors", []),
                               form_errors=errors,
                               form_name=name, form_email=email, form_message=message)

    db.session.add(ContactMessage(name=name, email=email, message=message))
    db.session.commit()

    cfg = _town_cfg()
    return render_template("main/about.html",
                           contact=cfg.get("contact", {}),
                           sponsors=cfg.get("sponsors", []),
                           form_sent=True)


# ── Verzoek om verwijdering ───────────────────────────────────────────────────

@bp.route("/verzoek-verwijdering", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def verzoek_verwijdering():
    from ...models import RemovalRequest
    if request.method != "POST":
        prefill = {
            "request_type": request.args.get("type", ""),
            "target":        request.args.get("target", ""),
        }
        return render_template("main/verzoek_verwijdering.html", prefill=prefill)

    rtype       = request.form.get("request_type", "").strip()
    target      = request.form.get("target", "").strip() or None
    description = request.form.get("description", "").strip()
    name        = request.form.get("contact_name", "").strip() or None
    email       = request.form.get("email", "").strip() or None
    phone       = request.form.get("phone", "").strip() or None
    phone_app   = request.form.get("phone_app", "").strip() or None

    errors = []
    if rtype not in ("tip", "url", "source"):
        errors.append("Kies een type verzoek.")
    if not description:
        errors.append("Omschrijving is verplicht.")
    if rtype in ("url", "source"):
        if not name:
            errors.append("Naam is verplicht voor dit type verzoek.")
        if not email and not phone:
            errors.append("Vul ten minste een e-mailadres of telefoonnummer in.")

    if errors:
        return render_template("main/verzoek_verwijdering.html",
                               errors=errors, form=request.form)

    db.session.add(RemovalRequest(
        request_type=rtype,
        target=target,
        description=description,
        contact_name=name,
        email=email,
        phone=phone,
        phone_app=phone_app,
    ))
    db.session.commit()
    return render_template("main/verzoek_verwijdering.html", sent=True)


# ── Uploaded images ───────────────────────────────────────────────────────────

@bp.route("/uploads/<path:filename>")
def uploaded_file(filename):
    """Serve editorial post images from the uploads directory."""
    from pathlib import Path
    safe_name = Path(filename).name  # strip any path traversal
    target = Config.uploads_path() / safe_name
    if not target.exists():
        abort(404)
    return send_file(target)


# ── Favicon proxy ─────────────────────────────────────────────────────────────

# Tiny grey square SVG used as fallback when a site has no /favicon.ico
_FAVICON_PLACEHOLDER = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
    b'<rect width="16" height="16" rx="3" fill="#ccc"/></svg>'
)


@bp.route("/favicon/<int:source_id>.png")
def source_favicon(source_id):
    """Serve a cached favicon fetched directly from the source domain."""
    import requests
    from urllib.parse import urlparse

    source = Source.query.get_or_404(source_id)

    favicon_dir = Config.town_cache_path().parent / "favicons"
    favicon_dir.mkdir(exist_ok=True)
    cache_path = favicon_dir / f"{source_id}.png"

    if cache_path.exists():
        return send_file(cache_path, mimetype="image/png")

    # Fetch directly from source domain — no third-party involved
    parsed = urlparse(source.base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    try:
        resp = requests.get(
            f"{origin}/favicon.ico",
            timeout=5,
            headers={"User-Agent": "LokaalNieuws/1.0"},
            allow_redirects=True,
            stream=True,
        )
        if resp.status_code == 200:
            content = resp.raw.read(256 * 1024 + 1, decode_content=True)
            if content and len(content) <= 256 * 1024:
                cache_path.write_bytes(content)
                return send_file(cache_path, mimetype=resp.headers.get("Content-Type", "image/x-icon"))
    except Exception:
        pass

    return Response(_FAVICON_PLACEHOLDER, mimetype="image/svg+xml")


# ── Site favicon ──────────────────────────────────────────────────────────────

@bp.route("/favicon.ico")
def favicon():
    from pathlib import Path
    ico = Path(current_app.static_folder) / "favicon.ico"
    if not ico.exists():
        abort(404)
    return send_file(ico, mimetype="image/x-icon")


# ── robots.txt ────────────────────────────────────────────────────────────────

@bp.route("/robots.txt")
def robots_txt():
    from pathlib import Path
    robots_file = Path(current_app.root_path).parent / "robots.txt"
    text = robots_file.read_text(encoding="utf-8") if robots_file.exists() else "User-agent: *\nDisallow: /admin/\n"
    site_url = Config.SITE_URL or request.url_root.rstrip("/")
    text = text.rstrip() + f"\n\nSitemap: {site_url}/sitemap.xml\n"
    return Response(text, mimetype="text/plain")


# ── sitemap.xml ───────────────────────────────────────────────────────────────

@bp.route("/sitemap.xml")
def sitemap_xml():
    from datetime import datetime, timezone
    from xml.sax.saxutils import escape

    site_url = Config.SITE_URL or request.url_root.rstrip("/")
    town_slug = current_app.jinja_env.globals.get("site_town", "").lower()

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _iso(dt):
        if dt is None:
            return now_iso
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%d")

    urls = []

    # Static pages
    static_pages = [
        ("/",              "daily",   "1.0"),
        ("/uitgelicht",    "daily",   "0.9"),
        ("/vandaag",       "daily",   "0.9"),
        ("/week",          "weekly",  "0.8"),
        (f"/{town_slug}",  "daily",   "0.9"),
        ("/regio",         "daily",   "0.8"),
        ("/provincie",     "daily",   "0.8"),
        ("/nationaal",     "daily",   "0.7"),
        ("/internationaal","daily",   "0.7"),
        ("/alles",         "daily",   "0.7"),
        ("/redactie",      "weekly",  "0.8"),
        ("/agenda",        "daily",   "0.7"),
        ("/ingezonden",    "weekly",  "0.6"),
        ("/over-ons",               "monthly", "0.5"),
        ("/verzoek-verwijdering",   "yearly",  "0.3"),
        ("/privacy",                "yearly",  "0.2"),
        ("/zoeken",        "weekly",  "0.4"),
    ]
    for path, freq, pri in static_pages:
        urls.append((escape(site_url + path), now_iso, freq, pri))

    # Redactional posts
    posts = RedactionalPost.query.order_by(RedactionalPost.published_at.desc()).all()
    for p in posts:
        urls.append((
            escape(f"{site_url}/redactie/{p.id}"),
            _iso(p.published_at),
            "never",
            "0.7",
        ))

    # Published opinions
    opinions = (
        Opinion.query
        .filter_by(status="published")
        .order_by(Opinion.published_at.desc())
        .all()
    )
    for o in opinions:
        urls.append((
            escape(f"{site_url}/ingezonden/{o.id}"),
            _iso(o.published_at),
            "never",
            "0.5",
        ))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod, freq, pri in urls:
        lines.append(
            f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod>"
            f"<changefreq>{freq}</changefreq><priority>{pri}</priority></url>"
        )
    lines.append("</urlset>")

    return Response("\n".join(lines), mimetype="application/xml")
