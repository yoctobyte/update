import json
from flask import render_template, request, abort, redirect, url_for, flash, current_app, send_file, Response
from . import bp
from ...models import Article, Story, Event, Topic, Opinion, ContactMessage, Source
from ...extensions import db, limiter
from ...config import Config


# ── helpers ───────────────────────────────────────────────────────────────────

def _town_cfg() -> dict:
    try:
        return json.loads(Config.town_config_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── News ──────────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    page = request.args.get("page", 1, type=int)
    topic_id = request.args.get("topic", type=int)

    query = (
        Article.query
        .join(Article.source)
        .filter_by(active=True)
        .filter(Article.geo_scope == "local")
        # Only publish once the AI rewrite is done
        .filter(Article.summary.isnot(None))
        .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
    )
    if topic_id:
        query = query.filter(Article.topics.any(id=topic_id))

    pagination = query.paginate(page=page, per_page=20, error_out=False)
    topics = Topic.query.order_by(Topic.name).all()
    active_topic = Topic.query.get(topic_id) if topic_id else None

    return render_template(
        "main/index.html",
        pagination=pagination,
        topics=topics,
        active_topic=active_topic,
    )


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

    return render_template(
        "main/article_detail.html",
        article=article,
        same_url_others=same_url_others,
        related_per_story=related_per_story,
        merge_logs=merge_logs,
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

    pagination = query.paginate(page=page, per_page=20, error_out=False)
    topics = Topic.query.order_by(Topic.name).all()
    active_topic = Topic.query.get(topic_id) if topic_id else None

    return render_template(
        "main/regio.html",
        pagination=pagination,
        topics=topics,
        active_topic=active_topic,
        region_towns=region_towns,
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

    pagination = query.paginate(page=page, per_page=20, error_out=False)
    topics = Topic.query.order_by(Topic.name).all()
    active_topic = Topic.query.get(topic_id) if topic_id else None

    return render_template(
        "main/provincie.html",
        pagination=pagination,
        topics=topics,
        active_topic=active_topic,
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

    pagination = query.paginate(page=page, per_page=20, error_out=False)
    topics = Topic.query.order_by(Topic.name).all()
    active_topic = Topic.query.get(topic_id) if topic_id else None

    return render_template(
        "main/nationaal.html",
        pagination=pagination,
        topics=topics,
        active_topic=active_topic,
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

    pagination = query.paginate(page=page, per_page=20, error_out=False)
    topics = Topic.query.order_by(Topic.name).all()
    active_topic = Topic.query.get(topic_id) if topic_id else None

    return render_template(
        "main/internationaal.html",
        pagination=pagination,
        topics=topics,
        active_topic=active_topic,
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

    pagination = query.paginate(page=page, per_page=20, error_out=False)
    topics = Topic.query.order_by(Topic.name).all()
    active_topic = Topic.query.get(topic_id) if topic_id else None

    return render_template(
        "main/alles.html",
        pagination=pagination,
        topics=topics,
        active_topic=active_topic,
    )


# ── Stories ───────────────────────────────────────────────────────────────────

@bp.route("/verhalen")
def stories():
    page = request.args.get("page", 1, type=int)
    pagination = (
        Story.query
        .filter_by(status="active")
        .order_by(Story.updated_at.desc())
        .paginate(page=page, per_page=20, error_out=False)
    )
    return render_template("main/stories.html", pagination=pagination)


@bp.route("/verhalen/<int:story_id>")
def story_detail(story_id):
    story = Story.query.get_or_404(story_id)
    articles = sorted(story.articles, key=lambda a: a.published_at or a.created_at, reverse=True)
    return render_template("main/story_detail.html", story=story, articles=articles)


# ── Events ────────────────────────────────────────────────────────────────────

@bp.route("/agenda")
def events():
    from datetime import datetime, timezone
    page = request.args.get("page", 1, type=int)
    topic_id = request.args.get("topic", type=int)
    now = datetime.now(timezone.utc)

    query = Event.query.filter(Event.start_time >= now).order_by(Event.start_time)
    if topic_id:
        query = query.filter(Event.topics.any(id=topic_id))

    pagination = query.paginate(page=page, per_page=20, error_out=False)
    topics = Topic.query.order_by(Topic.name).all()
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


# ── Opinion ───────────────────────────────────────────────────────────────────

@bp.route("/opinie")
def opinie_list():
    page = request.args.get("page", 1, type=int)
    pagination = (
        Opinion.query
        .filter_by(status="published")
        .order_by(Opinion.published_at.desc())
        .paginate(page=page, per_page=20, error_out=False)
    )
    return render_template("main/opinie_list.html", pagination=pagination)


@bp.route("/opinie/<int:opinion_id>")
def opinie_detail(opinion_id):
    opinion = Opinion.query.filter_by(id=opinion_id, status="published").first_or_404()
    return render_template("main/opinie_detail.html", opinion=opinion)


@bp.route("/opinie/insturen", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def opinie_insturen():
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

        edit_url = url_for("main.opinie_bewerken", token=opinion.token, _external=True)
        return render_template("main/opinie_ingezonden.html", opinion=opinion, edit_url=edit_url)

    return render_template("main/opinie_form.html", errors=[], pen_name="", title="", body="", email="")


@bp.route("/opinie/bewerken/<token>", methods=["GET", "POST"])
def opinie_bewerken(token):
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
        return redirect(url_for("main.opinie_bewerken", token=token))

    return render_template("main/opinie_bewerken.html", opinion=opinion, errors=[],
                           pen_name=opinion.pen_name, title=opinion.title, body=opinion.body)


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
