"""Fetch articles and events from RSS feeds, HTML sources, and agenda pages."""
import hashlib
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup

from ..extensions import db
from ..models import Source, Article, Event
from ..config import Config
from .browser import get_html as _browser_get_html, render_with_playwright as _render_with_playwright


logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
REQUEST_HEADERS = {
    "User-Agent": "LokaalNieuws/1.0 (local news aggregator)"
}


def _get_html(url: str, source: Source) -> str:
    """Fetch page HTML via Playwright or requests; always writes to disk cache."""
    html = _browser_get_html(url, source, skip_cache=True)
    if html is None:
        raise RuntimeError(f"Failed to fetch {url}")
    return html


def _normalize_url(url: str) -> str:
    """Strip fragments and trailing slashes for consistent hashing."""
    parsed = urlparse(url.strip())
    normalized = parsed._replace(fragment="")
    return urlunparse(normalized).rstrip("/")


def _url_hash(url: str, source_id: int | None = None) -> str:
    """
    Hash is scoped to source so the same URL can exist under multiple sources.
    e.g. an RSS snippet and a full article fetched by a link_page source
    are separate Article records that story clustering will connect.
    """
    key = f"{source_id}:{_normalize_url(url)}" if source_id else _normalize_url(url)
    return hashlib.sha256(key.encode()).hexdigest()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def fetch_source(source: Source) -> int:
    """Fetch a single source. Returns number of new items stored."""
    try:
        if source.type == "rss":
            new_count = _fetch_rss(source)
        elif source.type == "link_page":
            new_count = _fetch_link_page(source)
        elif source.type == "article_page":
            new_count = _fetch_article_page(source)
        elif source.type == "agenda":
            new_count = _fetch_agenda(source)
        else:
            logger.warning("Unknown source type '%s' for source %s", source.type, source.name)
            new_count = 0

        _update_source_status(source, success=True, new_count=new_count)
        logger.info("Fetched %s: %d new items", source.name, new_count)
        return new_count
    except Exception as exc:
        # Roll back any broken transaction before touching the session again.
        # Without this, accessing source.name (lazy load) on a session whose
        # transaction was rolled back raises PendingRollbackError.
        try:
            db.session.rollback()
        except Exception:
            pass
        source_name = source.name if source else "unknown"
        logger.error("Failed to fetch source %s: %s", source_name, exc)
        try:
            _update_source_status(source, success=False)
        except Exception:
            pass
        return 0


def fetch_all_active(app) -> None:
    """Fetch all active sources. Designed to be called from scheduler."""
    with app.app_context():
        sources = Source.query.filter_by(active=True).all()
        for source in sources:
            fetch_source(source)


def _fetch_rss(source: Source) -> int:
    """
    Parse RSS/Atom feed. Each entry is stored as an Article under this RSS source
    using the entry's own description as content — self-contained, no link-following.

    Additionally: if another configured source covers the same domain as the linked
    article URL, we also queue that URL under that source so it gets extracted with
    a content rule. The two resulting articles (RSS snippet + full text) are separate
    records that story clustering will connect by similarity.
    """
    if source.render_js:
        # Fetch the feed URL through Playwright (e.g. consent-walled feeds),
        # then hand the raw XML/HTML to feedparser instead of a URL.
        raw = _render_with_playwright(source.base_url, source.cookie_accept_selector or None)
        feed = feedparser.parse(raw)
    else:
        feed = feedparser.parse(source.base_url, request_headers=REQUEST_HEADERS)
    new_count = 0

    # Build domain → source map for cross-source queueing (active sources only)
    all_sources = Source.query.filter(Source.active == True, Source.id != source.id).all()
    domain_to_sources: dict[str, list[Source]] = {}
    for s in all_sources:
        netloc = urlparse(s.base_url).netloc
        domain_to_sources.setdefault(netloc, []).append(s)

    for entry in feed.entries:
        url = getattr(entry, "link", None)
        title = getattr(entry, "title", "")
        if not url or not title:
            continue

        # trusted_local sources are always local; others get classified by LLM at extraction time
        if source.trusted_local:
            geo_scope = "local"
        else:
            geo_scope = None

        published_at = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

        # Extract text from feed entry
        raw_content = (
            getattr(entry, "content", [{}])[0].get("value")
            or getattr(entry, "summary", None)
            or getattr(entry, "description", None)
            or ""
        )
        extracted_text = None
        if raw_content:
            soup = BeautifulSoup(raw_content, "lxml")
            extracted_text = soup.get_text(separator=" ", strip=True) or None

        # Store under RSS source (source-scoped hash)
        rss_hash = _url_hash(url, source.id)
        if not Article.query.filter_by(hash=rss_hash).first():
            db.session.add(Article(
                source_id=source.id,
                url=url,
                title=title,
                extracted_text=extracted_text,
                short_text=(extracted_text or "")[:300],
                summary=None,
                published_at=published_at,
                hash=rss_hash,
                geo_scope=geo_scope,
            ))
            new_count += 1

        # Also queue under any other source covering the same domain
        article_netloc = urlparse(url).netloc
        for other_source in domain_to_sources.get(article_netloc, []):
            other_hash = _url_hash(url, other_source.id)
            if not Article.query.filter_by(hash=other_hash).first():
                db.session.add(Article(
                    source_id=other_source.id,
                    url=url,
                    title=title,
                    published_at=published_at,
                    hash=other_hash,
                ))
                logger.debug("Queued %s under source '%s' from RSS", url, other_source.name)

    db.session.commit()
    return new_count


def _fetch_link_page(source: Source) -> int:
    """
    Scrape listing page to find article links, then store them.
    Uses approved 'links' extraction rules, falls back to heuristic.
    """
    from urllib.parse import urljoin
    from ..models import ExtractionRule
    from ..services import extractor as ext

    html = _get_html(source.base_url, source)

    # Combine results from ALL approved links rules
    links_rules = (
        ExtractionRule.query
        .filter_by(source_id=source.id, approved=True, rule_purpose="links")
        .order_by(ExtractionRule.created_at.asc())
        .all()
    )

    if links_rules:
        seen_urls = set()
        combined = []
        for rule in links_rules:
            if not rule.rule_definition:
                continue
            for url in ext.apply_links_rule(rule, html, source.base_url):
                if url not in seen_urls:
                    seen_urls.add(url)
                    combined.append(url)
        if combined:
            items = [{"url": u, "title": "", "published_at": None} for u in combined]
            return _store_new_articles(source, items)
        logger.warning("Links rules for %s returned no URLs — falling back to heuristic", source.name)

    # Heuristic fallback
    soup = BeautifulSoup(html, "lxml")
    base_netloc = urlparse(source.base_url).netloc
    items = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            href = urljoin(source.base_url, href)
        if urlparse(href).netloc != base_netloc:
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 10:
            continue
        norm = _normalize_url(href)
        if norm in seen:
            continue
        seen.add(norm)
        items.append({"url": href, "title": title, "published_at": None})
    return _store_new_articles(source, items)


def _fetch_article_page(source: Source) -> int:
    """
    Fetch a single URL that IS the article. Create a new Article only when
    the extracted content has changed since last fetch (hash comparison).
    All articles from the same source are linked to a Story named after the source.
    """
    from ..services import extractor as ext
    from ..models import Story
    from ..models.associations import article_stories

    html = _get_html(source.base_url, source)

    # Apply content rule to get the meaningful text
    rules = ext._active_rules(source, purpose="content")
    extracted_text = None
    for rule in rules:
        text = ext.apply_content_rule(rule, html)
        if text and len(text.strip()) > 50:
            extracted_text = text.strip()
            break

    if extracted_text is None:
        # No rule yet — extract raw body text for hashing
        soup = BeautifulSoup(html, "lxml")
        extracted_text = soup.get_text(separator=" ", strip=True)

    new_hash = _content_hash(extracted_text)
    if new_hash == source.last_content_hash:
        logger.debug("article_page source %s unchanged", source.name)
        return 0

    # Content changed — create a new Article
    url_hash = _url_hash(source.base_url + "|" + new_hash)

    if Article.query.filter_by(hash=url_hash).first():
        # Already stored this exact content version
        source.last_content_hash = new_hash
        db.session.commit()
        return 0

    # Find or create the Story for this source
    story = Story.query.filter_by(title=source.name).first()
    if not story:
        story = Story(title=source.name, status="active")
        db.session.add(story)
        db.session.flush()

    # Try to get title from page
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else source.name

    # trusted_local sources are always local; others get classified by LLM at extraction time
    geo_scope = "local" if source.trusted_local else None

    article = Article(
        source_id=source.id,
        url=source.base_url,
        title=title,
        extracted_text=extracted_text,
        short_text=extracted_text[:300],
        hash=url_hash,
        geo_scope=geo_scope,
    )
    db.session.add(article)
    db.session.flush()
    article.stories.append(story)

    source.last_content_hash = new_hash
    db.session.commit()
    return 1


def _fetch_agenda(source: Source) -> int:
    """
    Fetch an agenda/event listing page and extract structured Event objects.
    Deduplicates by title + start_time.
    Skips LLM extraction entirely when the page HTML hasn't changed since last fetch.
    """
    import hashlib
    from ..services import extractor as ext

    html = _get_html(source.base_url, source)
    if not html:
        return 0

    page_hash = hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest()
    if source.last_content_hash == page_hash:
        logger.debug("Agenda page unchanged for %s — skipping LLM", source.base_url)
        return 0
    source.last_content_hash = page_hash
    db.session.commit()

    event_dicts = ext.extract_events_from_html(source, html)
    if not event_dicts:
        return 0

    new_count = 0
    for ev_data in event_dicts:
        title = ev_data.get("title")
        start_time = ev_data.get("start_time")
        if not title or not start_time:
            continue

        # Parse start_time if string
        if isinstance(start_time, str):
            try:
                from dateutil import parser as dateparser  # noqa: PLC0415
                start_time = dateparser.parse(start_time)
            except ImportError:
                logger.error("python-dateutil is not installed — run: pip install python-dateutil")
                break
            except Exception:
                logger.warning("Could not parse start_time '%s' for event '%s'", start_time, title)
                continue

        # Parse end_time if present
        end_time = ev_data.get("end_time")
        if isinstance(end_time, str) and end_time:
            try:
                from dateutil import parser as dateparser  # noqa: PLC0415
                end_time = dateparser.parse(end_time)
            except (ImportError, Exception):
                end_time = None

        # Dedup by title + start_time.
        # Use no_autoflush so pending session adds don't trigger an INSERT
        # before we've finished building the batch — avoids "database is locked"
        # when another thread holds the write lock at this exact moment.
        with db.session.no_autoflush:
            existing = Event.query.filter_by(title=title, start_time=start_time).first()
        if existing:
            continue

        # location may be a dict (JSON-LD structured data) — flatten to string
        raw_loc = ev_data.get("location")
        if isinstance(raw_loc, dict):
            addr = raw_loc.get("address", raw_loc)
            if isinstance(addr, dict):
                raw_loc = ", ".join(filter(None, [
                    addr.get("streetAddress"), addr.get("addressLocality"),
                    addr.get("addressCountry"),
                ]))
            else:
                raw_loc = str(addr)
        elif isinstance(raw_loc, list):
            raw_loc = "; ".join(str(x) for x in raw_loc if x)

        event = Event(
            title=title,
            description=ev_data.get("description"),
            location=raw_loc or None,
            start_time=start_time,
            end_time=end_time,
            organizer=ev_data.get("organizer"),
            contact_info=ev_data.get("contact_info"),
            source_url=source.base_url,
        )
        db.session.add(event)
        new_count += 1

    db.session.commit()
    return new_count


def _store_new_articles(
    source: Source,
    items: list[dict],
) -> int:
    new_count = 0
    # trusted_local sources are always local; others get classified by LLM at extraction time
    default_geo_scope = "local" if source.trusted_local else None
    for item in items:
        url_hash = _url_hash(item["url"], source.id)
        if Article.query.filter_by(hash=url_hash).first():
            continue
        article = Article(
            source_id=source.id,
            url=item["url"],
            title=item.get("title") or "",
            published_at=item.get("published_at"),
            hash=url_hash,
            geo_scope=default_geo_scope,
        )
        db.session.add(article)
        new_count += 1
    db.session.commit()
    return new_count


def _update_source_status(source: Source, success: bool, new_count: int = 0) -> None:
    if success:
        source.last_successful_fetch = datetime.now(timezone.utc)
        source.consecutive_failures = 0
        source.last_fetch_new_count = new_count
    else:
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
    db.session.commit()
