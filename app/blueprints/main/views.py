import json
from flask import render_template, request, abort, redirect, url_for, flash, current_app, send_file, Response
from . import bp
from ...models import Article, Story, Event, Topic, Opinion, ContactMessage, Source, RedactionalPost
from ...extensions import db, limiter
from ...config import Config


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
        .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
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
        page_items=_inject_pins(pagination.items, "local", page),
    )


def lokaal():
    """Canonical local news view — registered at /<town_slug> by create_app."""
    return _lokaal_response()


@bp.route("/lokaal")
def lokaal_redirect():
    """Backward-compat alias: redirect to the canonical /<town_slug> URL."""
    town = current_app.jinja_env.globals.get("site_town", "").lower()
    if town:
        qs = request.query_string.decode()
        target = f"/{town}" + (f"?{qs}" if qs else "")
        return redirect(target, 301)
    return _lokaal_response()


@bp.route("/")
def index():
    """Root: serve frontpage when enabled, otherwise fall through to local news."""
    from ...services.frontpage import frontpage_enabled, get_current_frontpage
    from ...models import Source as _Source
    if frontpage_enabled():
        articles = get_current_frontpage()
        topics = Topic.query.order_by(Topic.name).all()
        return render_template(
            "main/frontpage.html",
            articles=articles,
            topics=topics,
            sources_by_url=_sources_by_url(articles),
            page_items=_inject_pins(articles, "frontpage", 1),
        )
    return _lokaal_response()


@bp.route("/nieuws/<int:article_id>")
def article_detail(article_id):
    article = Article.query.filter_by(id=article_id).filter(Article.summary.isnot(None)).first_or_404()

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

    # Vector similarity: 10 most related articles
    # Exclude story siblings (already in "Gerelateerde verhalen") and same-URL copies
    from ...services.clustering import find_similar_articles
    sibling_ids = {a.id for articles in related_per_story.values() for a in articles}
    sibling_ids |= {a.id for a in same_url_others}
    similar_articles = find_similar_articles(article, limit=10, exclude_ids=sibling_ids)

    return render_template(
        "main/article_detail.html",
        article=article,
        same_url_others=same_url_others,
        related_per_story=related_per_story,
        merge_logs=merge_logs,
        similar_articles=similar_articles,
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
        .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
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
        page_items=_inject_pins(pagination.items, "region", page),
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
        .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
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
        page_items=_inject_pins(pagination.items, "province", page),
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
        .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
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
        page_items=_inject_pins(pagination.items, "national", page),
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
        .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
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
        page_items=_inject_pins(pagination.items, "intl", page),
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
        .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
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
        page_items=_inject_pins(pagination.items, "alles", page),
    )


# ── Redactie — editorial posts ────────────────────────────────────────────────

@bp.route("/redactie")
def redactie():
    page = request.args.get("page", 1, type=int)
    pagination = (
        RedactionalPost.query
        .order_by(RedactionalPost.published_at.desc())
        .paginate(page=page, per_page=25, error_out=False)
    )
    return render_template("main/redactie.html", pagination=pagination)


@bp.route("/redactie/<int:post_id>")
def redactie_post(post_id):
    post = RedactionalPost.query.get_or_404(post_id)
    return render_template("main/redactie_post.html", post=post)


# ── Stories (dormant — kept for backward compat / future use) ─────────────────

@bp.route("/redactie/verhaal/<int:story_id>")
def redactie_detail(story_id):
    story = Story.query.get_or_404(story_id)
    articles = sorted(story.articles, key=lambda a: a.published_at or a.created_at, reverse=True)
    return render_template("main/story_detail.html", story=story, articles=articles)


@bp.route("/verhalen")
def verhalen_redirect():
    return redirect(url_for("main.redactie"), 301)


@bp.route("/verhalen/<int:story_id>")
def verhalen_detail_redirect(story_id):
    return redirect(url_for("main.redactie_detail", story_id=story_id), 301)


# ── Events ────────────────────────────────────────────────────────────────────

@bp.route("/agenda")
def events():
    from datetime import datetime
    page = request.args.get("page", 1, type=int)
    topic_id = request.args.get("topic", type=int)
    now = datetime.utcnow()  # naive UTC — matches how SQLite stores datetimes

    query = Event.query.filter(Event.start_time >= now).order_by(Event.start_time)
    if topic_id:
        query = query.filter(Event.topics.any(id=topic_id))

    pagination = query.paginate(page=page, per_page=min(request.args.get("per_page", 100, type=int), 200), error_out=False)
    topics = _section_topics("alles")
    active_topic = Topic.query.get(topic_id) if topic_id else None

    return render_template(
        "main/events.html",
        pagination=pagination,
        topics=topics,
        active_topic=active_topic,
    )


@bp.route("/agenda/<int:event_id>")
def event_detail(event_id):
    event = Event.query.get_or_404(event_id)
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
        )
        if resp.status_code == 200 and resp.content:
            cache_path.write_bytes(resp.content)
            return send_file(cache_path, mimetype=resp.headers.get("Content-Type", "image/x-icon"))
    except Exception:
        pass

    return Response(_FAVICON_PLACEHOLDER, mimetype="image/svg+xml")


# ── robots.txt ────────────────────────────────────────────────────────────────

@bp.route("/robots.txt")
def robots_txt():
    from pathlib import Path
    robots_file = Path(current_app.root_path).parent / "robots.txt"
    text = robots_file.read_text(encoding="utf-8") if robots_file.exists() else "User-agent: *\nDisallow: /admin/\n"
    return Response(text, mimetype="text/plain")
