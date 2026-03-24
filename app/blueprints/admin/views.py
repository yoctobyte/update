import functools
from datetime import datetime, timezone

from flask import (
    render_template, request, redirect, url_for,
    session, flash, abort, current_app
)

from . import bp
from ...extensions import db, limiter
from ...models import (
    Source, ExtractionRule, Story, StoryMergeLog,
    Article, Topic, Event, SuggestedTopic
)
from ...services import clustering, extractor, llm


# Required rule purposes per source type
_REQUIRED_PURPOSES = {
    "link_page":    {"links", "content"},
    "article_page": {"content"},
    "rss":          set(),
    "agenda":       {"events"},
}


# ── Auth ──────────────────────────────────────────────────────────────────────

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 30 per hour")
def login():
    if request.method == "POST":
        import bcrypt
        pw = request.form.get("password", "").encode()
        stored_hash = current_app.config.get("ADMIN_PASSWORD_HASH", "").encode()
        if not stored_hash:
            flash("Beheerderswachtwoord niet geconfigureerd. Voer ./changepassword.sh uit.", "error")
        elif bcrypt.checkpw(pw, stored_hash):
            session["admin_logged_in"] = True
            return redirect(url_for("admin.dashboard"))
        else:
            flash("Onjuist wachtwoord.", "error")
    return render_template("admin/login.html")


@bp.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("main.index"))


# ── Dashboard / Warnings ──────────────────────────────────────────────────────

@bp.route("/")
@login_required
def dashboard():
    failing_sources = Source.query.filter(Source.consecutive_failures > 0).all()
    pending_rules = ExtractionRule.query.filter_by(approved=False).filter(
        ExtractionRule.rule_definition != ""
    ).all()
    pending_merges = StoryMergeLog.query.filter_by(outcome="pending").count()
    article_count = Article.query.count()
    story_count = Story.query.filter_by(status="active").count()
    pending_topics = SuggestedTopic.query.filter_by(status="pending").count()

    return render_template(
        "admin/dashboard.html",
        failing_sources=failing_sources,
        pending_rules=pending_rules,
        pending_merges=pending_merges,
        article_count=article_count,
        story_count=story_count,
        pending_topics=pending_topics,
    )


# ── Sources ───────────────────────────────────────────────────────────────────

@bp.route("/bronnen")
@login_required
def sources():
    all_sources = Source.query.order_by(Source.name).all()
    article_counts = {s.id: s.articles.count() for s in all_sources}
    return render_template("admin/sources.html", sources=all_sources, article_counts=article_counts)


def _normalize_source_url(raw: str) -> str:
    """Prepend https:// if no protocol given."""
    raw = raw.strip()
    if raw and "://" not in raw:
        raw = "https://" + raw
    return raw


def _validate_source_url(url: str) -> str | None:
    """Return error string if URL is not safe to scrape, else None."""
    import ipaddress
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "Alleen http:// en https:// URLs zijn toegestaan."
    host = parsed.hostname or ""
    # Block IP literals pointing to private/loopback ranges
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            return "Interne IP-adressen zijn niet toegestaan als bron."
    except ValueError:
        pass  # hostname, not an IP literal — fine
    return None


@bp.route("/bronnen/nieuw", methods=["GET", "POST"])
@login_required
def source_new():
    if request.method == "POST":
        raw_url = request.form.get("url", "").strip()
        url = _normalize_source_url(raw_url)
        err = _validate_source_url(url)
        if err:
            flash(err, "error")
            return render_template("admin/source_form.html", source=None)
        name = request.form.get("name", "").strip() or raw_url
        src_type = request.form.get("type", "link_page")  # 'rss' | 'link_page' | 'article_page' | 'agenda'

        source = Source(
            name=name,
            base_url=url,
            type=src_type,
            search_depth=int(request.form.get("search_depth", 1)),
            filter_scope=request.form.get("filter_scope", "none"),
            trusted_local=bool(request.form.get("trusted_local")),
            render_js=bool(request.form.get("render_js")),
            cookie_accept_selector=request.form.get("cookie_accept_selector", "").strip() or None,
            active=False,
        )
        db.session.add(source)
        db.session.flush()  # get source.id before commit

        _create_initial_rules(source)
        db.session.commit()
        flash(f"Bron '{source.name}' toegevoegd — controleer en genereer de extractieregel.", "info")
        return redirect(url_for("admin.rules"))
    return render_template("admin/source_form.html", source=None)


@bp.route("/bronnen/<int:source_id>/bewerk", methods=["GET", "POST"])
@login_required
def source_edit(source_id):
    source = Source.query.get_or_404(source_id)
    if request.method == "POST":
        raw_url = request.form.get("url", "").strip()
        url = _normalize_source_url(raw_url)
        err = _validate_source_url(url)
        if err:
            flash(err, "error")
            return render_template("admin/source_form.html", source=source)
        source.name = request.form.get("name", "").strip() or raw_url
        source.base_url = url
        source.type = request.form.get("type", "link_page")
        source.search_depth = int(request.form.get("search_depth", 1))
        source.filter_scope = request.form.get("filter_scope", "none")
        source.trusted_local = bool(request.form.get("trusted_local"))
        source.render_js = bool(request.form.get("render_js"))
        source.cookie_accept_selector = request.form.get("cookie_accept_selector", "").strip() or None
        db.session.commit()
        flash("Bron opgeslagen.", "success")
        return redirect(url_for("admin.sources"))
    return render_template("admin/source_form.html", source=source)


@bp.route("/bronnen/<int:source_id>/toggle", methods=["POST"])
@login_required
def source_toggle(source_id):
    source = Source.query.get_or_404(source_id)
    source.active = not source.active
    db.session.commit()
    return render_template("admin/partials/source_row.html", source=source,
                           article_counts={source.id: source.articles.count()})


@bp.route("/bronnen/<int:source_id>/verwijder", methods=["POST"])
@login_required
def source_delete(source_id):
    source = Source.query.get_or_404(source_id)
    db.session.delete(source)
    db.session.commit()
    flash(f"Bron '{source.name}' verwijderd.", "info")
    return redirect(url_for("admin.sources"))


@bp.route("/bronnen/<int:source_id>/ophalen", methods=["POST"])
@login_required
def source_fetch_now(source_id):
    from ...services.fetcher import fetch_source
    from ...services.extractor import extract_all_pending
    source = Source.query.get_or_404(source_id)
    new_count = fetch_source(source)
    extract_all_pending(current_app._get_current_object())
    flash(f"Opgehaald: {new_count} nieuwe item(s) voor '{source.name}'.", "info")
    return redirect(url_for("admin.sources"))


# ── Extraction Rules ──────────────────────────────────────────────────────────

@bp.route("/regels")
@login_required
def rules():
    pending = ExtractionRule.query.filter_by(approved=False)\
        .order_by(ExtractionRule.created_at.desc()).all()

    # Sources missing rules they should have based on their type
    all_rules = ExtractionRule.query.all()
    covered = {}  # source_id -> set of purposes covered (pending or approved)
    for r in all_rules:
        covered.setdefault(r.source_id, set()).add(r.rule_purpose)

    unconfigured = []
    for source in Source.query.all():
        required = _REQUIRED_PURPOSES.get(source.type, set())
        purposes = covered.get(source.id, set())
        if not required.issubset(purposes):
            unconfigured.append(source)

    approved = ExtractionRule.query.filter_by(approved=True)\
        .order_by(ExtractionRule.source_id, ExtractionRule.rule_purpose, ExtractionRule.created_at.asc()).all()

    return render_template("admin/rules.html", pending_rules=pending, approved_rules=approved, unconfigured_sources=unconfigured)


@bp.route("/bronnen/<int:source_id>/init-regels", methods=["POST"])
@login_required
def source_init_rules(source_id):
    """Create blank pending extraction rules for any purpose the source is missing."""
    source = Source.query.get_or_404(source_id)
    existing_purposes = {
        r.rule_purpose for r in ExtractionRule.query.filter_by(source_id=source.id).all()
    }
    required = _REQUIRED_PURPOSES.get(source.type, set())
    for purpose in required - existing_purposes:
        db.session.add(ExtractionRule(
            source_id=source.id, rule_type="css_selector", rule_definition="",
            approved=False, scope="persistent", rule_purpose=purpose,
        ))
    db.session.commit()
    flash(f"Regels aangemaakt voor '{source.name}' — genereer ze hieronder.", "info")
    return redirect(url_for("admin.rules"))


@bp.route("/bronnen/<int:source_id>/extra-regel/<purpose>", methods=["POST"])
@login_required
def source_add_rule(source_id, purpose):
    """Add an extra blank rule for the same purpose (e.g. a second links selector)."""
    source = Source.query.get_or_404(source_id)
    if purpose not in ("links", "content", "events"):
        abort(400)
    db.session.add(ExtractionRule(
        source_id=source.id, rule_type="css_selector", rule_definition="",
        approved=False, scope="persistent", rule_purpose=purpose,
    ))
    db.session.commit()
    flash(f"Extra {purpose}regel aangemaakt voor '{source.name}'.", "info")
    return redirect(url_for("admin.rules"))


@bp.route("/regels/<int:rule_id>/voorbeeld")
@login_required
def rule_preview(rule_id):
    rule = ExtractionRule.query.get_or_404(rule_id)
    source = rule.source
    preview_text = None
    preview_links = None
    preview_events_count = None

    combined_links = None
    if rule.rule_definition:
        if rule.rule_purpose == "links":
            html = extractor.get_listing_html(source)
            if html:
                preview_links = extractor.apply_links_rule(rule, html, source.base_url)
                # Also show what all approved rules together would yield
                other_approved = ExtractionRule.query.filter(
                    ExtractionRule.source_id == source.id,
                    ExtractionRule.rule_purpose == "links",
                    ExtractionRule.approved == True,
                    ExtractionRule.id != rule.id,
                ).all()
                if other_approved:
                    seen = set(preview_links or [])
                    combined_links = list(preview_links or [])
                    for r in other_approved:
                        for u in extractor.apply_links_rule(r, html, source.base_url):
                            if u not in seen:
                                seen.add(u)
                                combined_links.append(u)
        elif rule.rule_purpose == "events":
            html = extractor.get_listing_html(source)
            if html:
                elements = extractor.apply_events_rule(rule, html)
                preview_events_count = len(elements)
        else:
            html = extractor.get_article_sample_html(source)
            if html:
                preview_text = extractor.apply_content_rule(rule, html)

    return render_template(
        "admin/rule_preview.html",
        rule=rule,
        source=source,
        preview_text=preview_text,
        preview_links=preview_links,
        combined_links=combined_links,
        preview_events_count=preview_events_count,
    )


@bp.route("/regels/<int:rule_id>/keur-goed", methods=["POST"])
@login_required
def rule_approve(rule_id):
    rule = ExtractionRule.query.get_or_404(rule_id)
    rule.approved = True
    rule.scope = request.form.get("scope", "persistent")
    db.session.commit()
    # HTMX request from rule_row: return empty string so the row is removed from the pending list
    if request.headers.get("HX-Request"):
        return ""
    # Regular POST from rule_preview page: redirect back to rules
    flash(f"Regel goedgekeurd voor '{rule.source.name}'.", "success")
    return redirect(url_for("admin.rules"))


@bp.route("/regels/<int:rule_id>/verwijder", methods=["POST"])
@login_required
def rule_delete(rule_id):
    rule = ExtractionRule.query.get_or_404(rule_id)
    source_name = rule.source.name
    db.session.delete(rule)
    db.session.commit()
    # HTMX request from rule_row: return empty string so the row disappears
    if request.headers.get("HX-Request"):
        return ""
    flash(f"Regel verwijderd voor '{source_name}'.", "info")
    return redirect(url_for("admin.rules"))


@bp.route("/bronnen/<int:source_id>/genereer-nieuw/<purpose>", methods=["POST"])
@login_required
def rule_generate_new(source_id, purpose):
    """Generate a brand-new pending rule for an approved source+purpose — never touch the live rule."""
    source = Source.query.get_or_404(source_id)
    if purpose not in ("links", "content", "events"):
        abort(400)
    new_rule = ExtractionRule(
        source_id=source.id, rule_type="css_selector", rule_definition="",
        approved=False, scope="persistent", rule_purpose=purpose,
    )
    db.session.add(new_rule)
    db.session.flush()
    # Redirect to the new rule's generate endpoint (which will do the actual AI call)
    return redirect(url_for("admin.rule_generate", rule_id=new_rule.id),
                    code=307)  # 307 preserves POST method + body (sample_url)


@bp.route("/regels/<int:rule_id>/genereer", methods=["POST"])
@login_required
def rule_generate(rule_id):
    rule = ExtractionRule.query.get_or_404(rule_id)
    source = rule.source

    # Safety: never overwrite an approved rule — the UI should route via rule_generate_new instead
    if rule.approved:
        flash("Kan een goedgekeurde regel niet overschrijven. Gebruik '+ Nieuwe variant genereren'.", "error")
        return redirect(url_for("admin.rule_preview", rule_id=rule.id))

    if rule.rule_purpose == "links":
        html_sample = extractor.get_listing_html(source)
        sample_url_used = source.base_url
        if not html_sample:
            flash("Kon de lijstpagina niet ophalen.", "error")
            return redirect(url_for("admin.rule_preview", rule_id=rule.id))
    elif rule.rule_purpose == "events":
        html_sample = extractor.get_listing_html(source)
        sample_url_used = source.base_url
        if not html_sample:
            flash("Kon de agendapagina niet ophalen.", "error")
            return redirect(url_for("admin.rule_preview", rule_id=rule.id))
    else:
        # For content rules: admin may supply a concrete article URL to use as sample
        sample_url_used = request.form.get("sample_url", "").strip()
        if sample_url_used:
            if "://" not in sample_url_used:
                sample_url_used = "https://" + sample_url_used
            html_sample = extractor._fetch_html(sample_url_used, source)
            if not html_sample:
                flash(f"Kon de opgegeven URL niet ophalen: {sample_url_used}", "error")
                return redirect(url_for("admin.rule_preview", rule_id=rule.id))
        else:
            html_sample = extractor.get_article_sample_html(source)
            sample_url_used = None
        if not html_sample:
            flash(
                "Geen artikelpagina beschikbaar als voorbeeld. "
                "Vul een artikel-URL in het veld hieronder in, of keur eerst de linkregel goed.",
                "error",
            )
            return redirect(url_for("admin.rule_preview", rule_id=rule.id))

    # Collect existing rule definitions for this source+purpose so the AI avoids duplicating them
    existing_definitions = [
        r.rule_definition for r in ExtractionRule.query.filter(
            ExtractionRule.source_id == source.id,
            ExtractionRule.rule_purpose == rule.rule_purpose,
            ExtractionRule.id != rule.id,
            ExtractionRule.rule_definition != "",
        ).all()
    ]

    # Truncate for the LLM — full HTML can be 100 KB+; 15 000 chars is plenty for structure analysis
    LLM_HTML_LIMIT = 15_000
    result = llm.generate_extraction_rule(
        sample_url_used or source.base_url, html_sample[:LLM_HTML_LIMIT],
        purpose=rule.rule_purpose,
        existing_rules=existing_definitions,
    )
    if result:
        rule.rule_type = result["rule_type"]
        rule.rule_definition = result["rule_definition"]
        db.session.commit()
        flash("Regel gegenereerd — controleer het voorbeeld.", "info")
    else:
        flash("AI kon geen regel genereren.", "error")
    return redirect(url_for("admin.rule_preview", rule_id=rule.id))


# ── Story merge queue ─────────────────────────────────────────────────────────

@bp.route("/samenvoegen")
@login_required
def merge_queue():
    page = request.args.get("page", 1, type=int)
    pagination = (
        StoryMergeLog.query
        .filter_by(outcome="pending")
        .order_by(StoryMergeLog.created_at.desc())
        .paginate(page=page, per_page=20, error_out=False)
    )
    return render_template("admin/merge_queue.html", pagination=pagination)


@bp.route("/samenvoegen/log")
@login_required
def merge_log():
    page = request.args.get("page", 1, type=int)
    pagination = (
        StoryMergeLog.query
        .order_by(StoryMergeLog.created_at.desc())
        .paginate(page=page, per_page=50, error_out=False)
    )
    return render_template("admin/merge_log.html", pagination=pagination)


@bp.route("/samenvoegen/<int:log_id>/accepteer", methods=["POST"])
@login_required
def merge_accept(log_id):
    log = StoryMergeLog.query.get_or_404(log_id)
    article = log.article
    story = log.story
    if story not in article.stories:
        article.stories.append(story)
    log.outcome = "merged"
    log.resolved_by = "admin"
    log.resolved_at = datetime.now(timezone.utc)
    db.session.commit()
    return render_template("admin/partials/merge_item.html", log=log)


@bp.route("/samenvoegen/<int:log_id>/weiger", methods=["POST"])
@login_required
def merge_reject(log_id):
    log = StoryMergeLog.query.get_or_404(log_id)
    log.outcome = "rejected"
    log.resolved_by = "admin"
    log.resolved_at = datetime.now(timezone.utc)
    db.session.commit()
    return render_template("admin/partials/merge_item.html", log=log)


@bp.route("/verhalen/<int:story_id>/ontkoppel/<int:article_id>", methods=["POST"])
@login_required
def story_untie(story_id, article_id):
    clustering.untie_article_from_story(article_id, story_id)
    return redirect(url_for("admin.story_edit", story_id=story_id))


# ── Stories ───────────────────────────────────────────────────────────────────

@bp.route("/verhalen")
@login_required
def stories():
    stories = Story.query.order_by(Story.updated_at.desc()).all()
    return render_template("admin/stories.html", stories=stories)


@bp.route("/verhalen/<int:story_id>", methods=["GET", "POST"])
@login_required
def story_edit(story_id):
    story = Story.query.get_or_404(story_id)
    topics = Topic.query.order_by(Topic.name).all()
    if request.method == "POST":
        story.title = request.form["title"]
        story.description = request.form.get("description")
        story.further_reading = request.form.get("further_reading")
        story.status = request.form.get("status", "active")
        topic_ids = request.form.getlist("topic_ids", type=int)
        story.topics = Topic.query.filter(Topic.id.in_(topic_ids)).all()
        db.session.commit()
        flash("Verhaal opgeslagen.", "success")
        return redirect(url_for("admin.story_edit", story_id=story.id))
    return render_template("admin/story_edit.html", story=story, topics=topics)


@bp.route("/verhalen/<int:story_id>/samenvatting", methods=["POST"])
@login_required
def story_summarize(story_id):
    story = Story.query.get_or_404(story_id)
    texts = [a.extracted_text for a in story.articles if a.extracted_text]
    if len(texts) < 2:
        flash("Minimaal 2 artikelen met tekst nodig voor samenvatting.", "error")
        return redirect(url_for("admin.story_edit", story_id=story_id))
    summary = llm.summarize_story(texts)
    if summary:
        story.description = summary
        db.session.commit()
        flash("Samenvatting gegenereerd.", "success")
    else:
        flash("AI kon geen samenvatting genereren.", "error")
    return redirect(url_for("admin.story_edit", story_id=story_id))


# ── Statistics ───────────────────────────────────────────────────────────────

@bp.route("/statistieken")
@login_required
def stats():
    from sqlalchemy import func
    from ...models import Article

    sources = Source.query.order_by(Source.name).all()

    # Total article count per source
    counts = dict(
        db.session.query(Article.source_id, func.count(Article.id))
        .group_by(Article.source_id)
        .all()
    )

    # Oldest and newest article date per source
    oldest = dict(
        db.session.query(Article.source_id, func.min(Article.created_at))
        .group_by(Article.source_id)
        .all()
    )
    newest = dict(
        db.session.query(Article.source_id, func.max(Article.created_at))
        .group_by(Article.source_id)
        .all()
    )

    rows = []
    for s in sources:
        rows.append({
            "source":      s,
            "total":       counts.get(s.id, 0),
            "last_new":    s.last_fetch_new_count,
            "last_fetch":  s.last_successful_fetch,
            "failures":    s.consecutive_failures or 0,
            "first_seen":  oldest.get(s.id),
            "last_seen":   newest.get(s.id),
        })

    # Sort: failing first, then by total desc
    rows.sort(key=lambda r: (-r["failures"], -r["total"]))

    return render_template("admin/stats.html", rows=rows)


# ── Site settings (config.json) ───────────────────────────────────────────────

@bp.route("/instellingen", methods=["GET", "POST"])
@login_required
def settings():
    import json
    from ...config import Config

    cfg_path = Config.town_config_path()
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}

    if request.method == "POST":
        # Region towns: one per line, strip blanks
        raw = request.form.get("region_towns", "")
        towns = [t.strip() for t in raw.splitlines() if t.strip()]
        cfg["region_towns"] = towns
        # Province name
        cfg["province"] = request.form.get("province", "").strip()
        # Province towns: one per line, strip blanks
        raw_pt = request.form.get("province_towns", "")
        province_towns = [t.strip() for t in raw_pt.splitlines() if t.strip()]
        cfg["province_towns"] = province_towns
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        flash("Instellingen opgeslagen.", "success")
        return redirect(url_for("admin.settings"))

    region_towns_text = "\n".join(cfg.get("region_towns", []))
    province_towns_text = "\n".join(cfg.get("province_towns", []))
    return render_template(
        "admin/settings.html",
        cfg=cfg,
        region_towns_text=region_towns_text,
        province_towns_text=province_towns_text,
    )


# ── Topics ────────────────────────────────────────────────────────────────────

@bp.route("/onderwerpen")
@login_required
def topics():
    all_topics = Topic.query.order_by(Topic.name).all()
    return render_template("admin/topics.html", topics=all_topics)


@bp.route("/onderwerpen/nieuw", methods=["POST"])
@login_required
def topic_new():
    name = request.form.get("name", "").strip()
    if name:
        existing = Topic.query.filter_by(name=name).first()
        if not existing:
            db.session.add(Topic(name=name, description=request.form.get("description")))
            db.session.commit()
    return redirect(url_for("admin.topics"))


@bp.route("/onderwerpen/<int:topic_id>/verwijder", methods=["POST"])
@login_required
def topic_delete(topic_id):
    topic = Topic.query.get_or_404(topic_id)
    db.session.delete(topic)
    db.session.commit()
    return redirect(url_for("admin.topics"))


# ── Suggested Topics ──────────────────────────────────────────────────────────

@bp.route("/onderwerpen/suggesties")
@login_required
def suggested_topics():
    pending = SuggestedTopic.query.filter_by(status="pending").order_by(
        SuggestedTopic.article_count.desc()
    ).all()
    return render_template("admin/suggested_topics.html", suggestions=pending)


@bp.route("/onderwerpen/suggesties/<int:suggestion_id>/keur-goed", methods=["POST"])
@login_required
def suggested_topic_approve(suggestion_id):
    suggestion = SuggestedTopic.query.get_or_404(suggestion_id)
    name = request.form.get("name", suggestion.name).strip()

    # Create real Topic (or find existing one with this name)
    topic = Topic.query.filter(db.func.lower(Topic.name) == name.lower()).first()
    if topic is None:
        topic = Topic(name=name)
        db.session.add(topic)
        db.session.flush()

    # Tag all articles that triggered this suggestion
    for article in suggestion.articles:
        if topic not in article.topics:
            article.topics.append(topic)

    suggestion.status = "approved"
    db.session.commit()
    flash(f"Onderwerp '{topic.name}' aangemaakt en toegewezen aan {suggestion.article_count} artikel(en).", "success")
    return redirect(url_for("admin.suggested_topics"))


@bp.route("/onderwerpen/suggesties/<int:suggestion_id>/afwijzen", methods=["POST"])
@login_required
def suggested_topic_reject(suggestion_id):
    suggestion = SuggestedTopic.query.get_or_404(suggestion_id)
    suggestion.status = "rejected"
    db.session.commit()
    return redirect(url_for("admin.suggested_topics"))


# ── Events ────────────────────────────────────────────────────────────────────

@bp.route("/agenda")
@login_required
def events():
    all_events = Event.query.order_by(Event.start_time.desc()).all()
    topics = Topic.query.order_by(Topic.name).all()
    return render_template("admin/events.html", events=all_events, topics=topics)


@bp.route("/agenda/nieuw", methods=["GET", "POST"])
@login_required
def event_new():
    topics = Topic.query.order_by(Topic.name).all()
    if request.method == "POST":
        from dateutil import parser as dateparser
        event = Event(
            title=request.form["title"],
            description=request.form.get("description"),
            location=request.form.get("location"),
            start_time=dateparser.parse(request.form["start_time"]),
            end_time=dateparser.parse(request.form["end_time"]) if request.form.get("end_time") else None,
            organizer=request.form.get("organizer"),
            contact_info=request.form.get("contact_info"),
            source_url=request.form.get("source_url"),
        )
        topic_ids = request.form.getlist("topic_ids", type=int)
        event.topics = Topic.query.filter(Topic.id.in_(topic_ids)).all()
        db.session.add(event)
        db.session.commit()
        flash("Evenement toegevoegd.", "success")
        return redirect(url_for("admin.events"))
    return render_template("admin/event_form.html", event=None, topics=topics)


@bp.route("/agenda/<int:event_id>/bewerk", methods=["GET", "POST"])
@login_required
def event_edit(event_id):
    event = Event.query.get_or_404(event_id)
    topics = Topic.query.order_by(Topic.name).all()
    if request.method == "POST":
        from dateutil import parser as dateparser
        event.title = request.form["title"]
        event.description = request.form.get("description")
        event.location = request.form.get("location")
        event.start_time = dateparser.parse(request.form["start_time"])
        event.end_time = dateparser.parse(request.form["end_time"]) if request.form.get("end_time") else None
        event.organizer = request.form.get("organizer")
        event.contact_info = request.form.get("contact_info")
        event.source_url = request.form.get("source_url")
        topic_ids = request.form.getlist("topic_ids", type=int)
        event.topics = Topic.query.filter(Topic.id.in_(topic_ids)).all()
        db.session.commit()
        flash("Evenement opgeslagen.", "success")
        return redirect(url_for("admin.events"))
    return render_template("admin/event_form.html", event=event, topics=topics)


@bp.route("/agenda/<int:event_id>/verwijder", methods=["POST"])
@login_required
def event_delete(event_id):
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    return redirect(url_for("admin.events"))


# ── Opinion moderation ────────────────────────────────────────────────────────

@bp.route("/opinie")
@login_required
def opinie():
    from ...models import Opinion, ContactMessage
    pending   = Opinion.query.filter_by(status="pending").order_by(Opinion.created_at.asc()).all()
    published = Opinion.query.filter_by(status="published").order_by(Opinion.published_at.desc()).limit(20).all()
    contact_messages = ContactMessage.query.order_by(ContactMessage.read.asc(), ContactMessage.created_at.desc()).limit(50).all()
    return render_template("admin/opinie.html",
                           pending=pending, published=published,
                           contact_messages=contact_messages)


@bp.route("/opinie/<int:opinion_id>/approve", methods=["POST"])
@login_required
def opinie_approve(opinion_id):
    from ...models import Opinion
    from datetime import datetime, timezone
    op = Opinion.query.get_or_404(opinion_id)
    op.status       = "published"
    op.published_at = datetime.now(timezone.utc)
    db.session.commit()
    flash(f'"{op.title}" gepubliceerd.', "success")
    return redirect(url_for("admin.opinie"))


@bp.route("/opinie/<int:opinion_id>/reject", methods=["POST"])
@login_required
def opinie_reject(opinion_id):
    from ...models import Opinion
    op = Opinion.query.get_or_404(opinion_id)
    op.status = "rejected"
    db.session.commit()
    flash(f'"{op.title}" afgewezen / ingetrokken.', "info")
    return redirect(url_for("admin.opinie"))


@bp.route("/contact/<int:msg_id>/read", methods=["POST"])
@login_required
def contact_read(msg_id):
    from ...models import ContactMessage
    msg = ContactMessage.query.get_or_404(msg_id)
    msg.read = True
    db.session.commit()
    return redirect(url_for("admin.opinie"))


@bp.route("/regels/<int:rule_id>/bewerk", methods=["POST"])
@login_required
def rule_edit(rule_id):
    """Save a manually edited rule definition."""
    rule = ExtractionRule.query.get_or_404(rule_id)
    rule.rule_type = request.form.get("rule_type", rule.rule_type)
    rule.rule_definition = request.form.get("rule_definition", "").strip()
    db.session.commit()
    flash("Regel opgeslagen — controleer het voorbeeld.", "info")
    return redirect(url_for("admin.rule_preview", rule_id=rule.id))


@bp.route("/regels/<int:rule_id>/heuristiek", methods=["POST"])
@login_required
def rule_suggest_heuristic(rule_id):
    """Generate a rule using algorithmic pattern analysis (no LLM)."""
    rule = ExtractionRule.query.get_or_404(rule_id)
    source = rule.source

    if rule.approved:
        flash("Kan een goedgekeurde regel niet overschrijven. Gebruik '+ Nieuwe variant genereren'.", "error")
        return redirect(url_for("admin.rule_preview", rule_id=rule.id))

    if rule.rule_purpose in ("links", "events"):
        html = extractor.get_listing_html(source)
    else:
        sample_url = request.form.get("sample_url", "").strip()
        if sample_url:
            if "://" not in sample_url:
                sample_url = "https://" + sample_url
            html = extractor._fetch_html(sample_url, source)
        else:
            html = extractor.get_article_sample_html(source)

    if not html:
        flash("Kon de pagina niet ophalen voor analyse.", "error")
        return redirect(url_for("admin.rule_preview", rule_id=rule.id))

    result = extractor.suggest_rule_heuristic(source, rule.rule_purpose, html)
    if result:
        rule.rule_type = result["rule_type"]
        rule.rule_definition = result["rule_definition"]
        db.session.commit()
        flash("Heuristisch gegenereerd — controleer het voorbeeld en pas zo nodig aan.", "info")
    else:
        flash("Geen duidelijk patroon gevonden. Voer de selector handmatig in.", "error")
    return redirect(url_for("admin.rule_preview", rule_id=rule.id))


@bp.route("/bronnen/<int:source_id>/heuristiek-nieuw/<purpose>", methods=["POST"])
@login_required
def rule_suggest_heuristic_new(source_id, purpose):
    """Create a new pending rule and fill it via heuristic analysis."""
    source = Source.query.get_or_404(source_id)
    if purpose not in ("links", "content", "events"):
        abort(400)
    new_rule = ExtractionRule(
        source_id=source.id, rule_type="css_selector", rule_definition="",
        approved=False, scope="persistent", rule_purpose=purpose,
    )
    db.session.add(new_rule)
    db.session.flush()
    return redirect(url_for("admin.rule_suggest_heuristic", rule_id=new_rule.id), code=307)


# ── Watched URLs ──────────────────────────────────────────────────────────────

@bp.route("/volgen")
@login_required
def watched_urls():
    from ...models import WatchedURL
    from ...services.watcher import snapshot_count
    entries = WatchedURL.query.order_by(WatchedURL.created_at.desc()).all()
    counts = {e.id: snapshot_count(e.url) for e in entries}
    return render_template("admin/watched_urls.html", entries=entries, counts=counts)


@bp.route("/volgen/nieuw", methods=["POST"])
@login_required
def watched_url_new():
    from ...models import WatchedURL
    url = request.form.get("url", "").strip()
    if url and "://" not in url:
        url = "https://" + url
    label = request.form.get("label", "").strip() or None
    render_js = bool(request.form.get("render_js"))
    if url:
        if not WatchedURL.query.filter_by(url=url).first():
            db.session.add(WatchedURL(url=url, label=label, render_js=render_js))
            db.session.commit()
            flash("URL toegevoegd.", "success")
        else:
            flash("URL staat al in de lijst.", "info")
    return redirect(url_for("admin.watched_urls"))


@bp.route("/volgen/<int:entry_id>/verwijder", methods=["POST"])
@login_required
def watched_url_delete(entry_id):
    from ...models import WatchedURL
    entry = WatchedURL.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash("URL verwijderd.", "info")
    return redirect(url_for("admin.watched_urls"))


@bp.route("/volgen/<int:entry_id>/toggle", methods=["POST"])
@login_required
def watched_url_toggle(entry_id):
    from ...models import WatchedURL
    entry = WatchedURL.query.get_or_404(entry_id)
    entry.active = not entry.active
    db.session.commit()
    return redirect(url_for("admin.watched_urls"))


@bp.route("/volgen/<int:entry_id>/ophalen", methods=["POST"])
@login_required
def watched_url_fetch(entry_id):
    from ...models import WatchedURL
    from ...services.watcher import fetch_watched_url
    from datetime import datetime, timezone
    entry = WatchedURL.query.get_or_404(entry_id)
    ok = fetch_watched_url(entry)
    if ok:
        entry.last_fetched_at = datetime.now(timezone.utc)
        db.session.commit()
        flash(f"Snapshot opgeslagen voor '{entry.label or entry.url[:60]}'.", "success")
    else:
        flash("Kon de URL niet ophalen.", "error")
    return redirect(url_for("admin.watched_urls"))


@bp.route("/volgen/ophalen-alles", methods=["POST"])
@login_required
def watched_urls_fetch_all():
    from ...models import WatchedURL
    from ...services.watcher import fetch_watched_url
    from datetime import datetime, timezone
    entries = WatchedURL.query.filter_by(active=True).all()
    ok_count = 0
    for entry in entries:
        if fetch_watched_url(entry):
            entry.last_fetched_at = datetime.now(timezone.utc)
            ok_count += 1
    db.session.commit()
    flash(f"{ok_count} van {len(entries)} URL's opgehaald.", "success")
    return redirect(url_for("admin.watched_urls"))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _create_initial_rules(source: Source) -> None:
    """Create blank pending extraction rules for a newly created source."""
    required = _REQUIRED_PURPOSES.get(source.type, set())
    for purpose in required:
        db.session.add(ExtractionRule(
            source_id=source.id, rule_type="css_selector", rule_definition="",
            approved=False, scope="persistent", rule_purpose=purpose,
        ))
