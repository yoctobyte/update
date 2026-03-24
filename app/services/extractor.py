"""Extract article text, article links, and events using per-source rules."""
import hashlib
import re
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..extensions import db
from ..models import Article, ExtractionRule, Source, Topic, SuggestedTopic
from ..config import Config
from .llm import rewrite_article, suggest_topics
from .browser import get_html as _browser_get_html, read_cache as _read_cache

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
REQUEST_HEADERS = {"User-Agent": "LokaalNieuws/1.0 (local news aggregator)"}


# ── Public API ────────────────────────────────────────────────────────────────

def extract_article(article: Article) -> bool:
    """
    Extract and summarise an article.

    RSS sources: the feed entry IS the complete article. Summarise from the
    stored description immediately — never follow the linked URL.
    If you want the full article from that domain, add it as a separate
    link_page source; story clustering will connect them.

    All other sources: fetch the article URL, apply content rule, summarise.
    If no rule works, create a placeholder rule for admin to configure.

    Returns True when a summary was successfully written.
    """
    _MAX_ATTEMPTS = 5

    source = article.source

    # ── RSS: self-contained, no URL fetching ──────────────────────────────────
    if source.type == "rss":
        if article.extracted_text:
            geo_ctx = Config.geo_context()
            existing_topic_names = [t.name for t in Topic.query.order_by(Topic.name).all()]
            result = rewrite_article(article.title, article.extracted_text, geo_ctx, existing_topic_names)
            if result:
                new_title, summary, geo_scope, topic_labels = result
                article.title = new_title
                article.summary = summary
                if source.trusted_local:
                    article.geo_scope = "local"
                else:
                    geo_scope = _verify_geo_scope(
                        geo_scope, article.title,
                        article.extracted_text or "", geo_ctx,
                    )
                    article.geo_scope = geo_scope
                _apply_topic_labels(article, topic_labels)
                db.session.commit()
                return True
        return False

    # ── All other types: fetch URL and apply content rule ─────────────────────
    article.extract_attempts = (article.extract_attempts or 0) + 1
    if article.extract_attempts >= _MAX_ATTEMPTS:
        article.skip_extraction = True
        db.session.commit()
        logger.warning("Giving up on %s after %d attempts", article.url, article.extract_attempts)
        return False

    rules = _active_rules(source, purpose="content")

    html = _fetch_html(article.url, source)
    if html is None:
        db.session.commit()  # persist incremented attempt count
        logger.warning("Could not fetch %s", article.url)
        return False
    # cache_html is now handled inside _fetch_html / browser.get_html

    # If we have no title yet, extract one from the page as a hint for the LLM.
    # Don't persist it — rewrite_article will produce the final title.
    if not article.title or not article.title.strip():
        soup_title = BeautifulSoup(html, "lxml")
        h1_tag = soup_title.find("h1")
        title_tag = soup_title.find("title")
        article.title = (
            (h1_tag.get_text(strip=True) if h1_tag else None)
            or (title_tag.get_text(strip=True) if title_tag else None)
            or article.url
        )[:500]

    geo_ctx = Config.geo_context()
    existing_topic_names = [t.name for t in Topic.query.order_by(Topic.name).all()]
    for rule in rules:
        text = apply_content_rule(rule, html)
        if text and len(text.strip()) > 50:
            article.extracted_text = text.strip()
            article.short_text = text.strip()[:300]
            result = rewrite_article(article.title, article.extracted_text, geo_ctx, existing_topic_names)
            if result:
                new_title, summary, geo_scope, topic_labels = result
                article.title = new_title
                article.summary = summary
                if source.trusted_local:
                    article.geo_scope = "local"
                else:
                    geo_scope = _verify_geo_scope(
                        geo_scope, article.title,
                        article.extracted_text or "", geo_ctx,
                    )
                    article.geo_scope = geo_scope
                _apply_topic_labels(article, topic_labels)
            if rule.scope == "once":
                rule.valid_until = db.func.now()
            db.session.commit()
            return True

    # No rule worked — create placeholder so it appears in admin rules page
    has_any_rule = ExtractionRule.query.filter_by(
        source_id=source.id, rule_purpose="content"
    ).first()
    if not has_any_rule:
        logger.info("No content rule for source %s — flagging for AI generation", source.name)
        db.session.add(ExtractionRule(
            source_id=source.id,
            rule_type="css_selector",
            rule_definition="",
            approved=False,
            scope="persistent",
            rule_purpose="content",
        ))
        db.session.commit()

    return False


def extract_all_pending(app) -> None:
    """
    Extract/upgrade text for articles that need it. Called from scheduler.
    - Articles with no content at all: must extract
    - RSS articles with only description content (no summary yet upgraded from full fetch):
      try to upgrade to full article text
    Both are identified by absence of a summary (summary is only set after a successful
    full extraction or RSS rewrite — so missing summary = worth trying again).
    """
    with app.app_context():
        articles = (
            Article.query
            .filter(Article.summary.is_(None), Article.skip_extraction == False)
            .limit(50).all()
        )
        for article in articles:
            extract_article(article)


def tag_untagged_articles(app, batch: int = 30) -> int:
    """
    Assign topics to articles that have a summary but no topics yet.
    Uses the fast LLM model. Called from scheduler and CLI.
    Returns number of articles tagged.
    """
    with app.app_context():
        existing_topics = Topic.query.order_by(Topic.name).all()
        if not existing_topics:
            return 0
        topic_names = [t.name for t in existing_topics]
        topic_map = {t.name.lower(): t for t in existing_topics}

        untagged = (
            Article.query
            .filter(Article.summary.isnot(None))
            .filter(~Article.topics.any())
            .order_by(Article.created_at.desc())
            .limit(batch)
            .all()
        )

        overig = topic_map.get("overig")

        tagged = 0
        for article in untagged:
            matches = suggest_topics(
                article.title,
                article.summary,
                topic_names,
            )
            for name in matches:
                topic = topic_map.get(name.lower())
                if topic and topic not in article.topics:
                    article.topics.append(topic)
            if not matches and overig and overig not in article.topics:
                article.topics.append(overig)
            if matches or overig:
                tagged += 1

        db.session.commit()
        logger.info("Tagged %d/%d untagged articles with existing topics", tagged, len(untagged))
        return tagged


def suggest_rule_heuristic(source: "Source", purpose: str, html: str) -> dict | None:
    """
    Suggest a CSS selector rule using pattern analysis — no LLM needed.
    Returns {'rule_type': 'css_selector', 'rule_definition': '...'} or None.
    """
    soup = BeautifulSoup(html, "lxml")
    if purpose == "links":
        return _heuristic_links_rule(soup, source.base_url)
    elif purpose == "content":
        return _heuristic_content_rule(soup)
    elif purpose == "events":
        return _heuristic_events_rule(soup)
    return None


def extract_events_from_html(source: Source, html: str) -> list[dict]:
    """
    Extract structured event dicts from an agenda page.

    Strategy:
    1. If an approved 'events' CSS selector rule exists, use it to find containers.
    2. Otherwise, run the repeating-pattern heuristic to find candidate containers.
    3. For each container element, call the LLM to parse it into a structured dict.

    Returns a list of dicts with keys:
      title, start_time, end_time, location, description, organizer, contact_info
    """
    from .llm import parse_event_html

    soup = BeautifulSoup(html, "lxml")
    elements = []

    # 1. Try approved events rule first
    rules = _active_rules(source, purpose="events")
    if rules:
        try:
            rule = rules[0]
            if rule.rule_type == "css_selector" and rule.rule_definition:
                elements = soup.select(rule.rule_definition)
                logger.info("Events rule found %d containers for %s", len(elements), source.name)
        except Exception as exc:
            logger.warning("Events rule %s failed: %s", rules[0].id, exc)

    # 2. Fall back to repeating-pattern heuristic
    if not elements:
        elements = _find_repeating_event_containers(soup)
        logger.info("Pattern heuristic found %d candidate containers for %s", len(elements), source.name)

    if not elements:
        logger.warning("No event containers found for %s", source.name)
        return []

    results = []
    for el in elements:
        event_data = parse_event_html(str(el))
        if event_data:
            results.append(event_data)

    return results


def _find_repeating_event_containers(soup: "BeautifulSoup") -> list:
    """
    Heuristic: find elements that repeat with the same tag+class combination,
    suggesting they are list items (e.g. event cards, agenda rows).

    Logic:
    - Count occurrences of each (tag, frozenset(classes)) combination
    - Keep combinations that appear 3+ times
    - Return the elements of the most common repeating pattern
    - Prefer deeper elements (more specific) over shallow ones
    - Skip generic containers (body, html, div with no class, nav, header, footer)
    """
    from collections import Counter

    SKIP_TAGS = {"html", "body", "head", "nav", "header", "footer", "script", "style"}
    MIN_REPEATS = 3

    counter: Counter = Counter()
    for el in soup.find_all(True):
        if el.name in SKIP_TAGS:
            continue
        classes = frozenset(el.get("class") or [])
        if not classes and el.name in {"div", "span", "section"}:
            continue  # skip classless generic containers
        key = (el.name, classes)
        counter[key] += 1

    # Find all patterns that repeat enough
    candidates = [(key, count) for key, count in counter.items() if count >= MIN_REPEATS]
    if not candidates:
        return []

    # Sort: semantic content tags (article, li, tr) first; then by class count; then frequency.
    # This prevents UI widgets with many classes (e.g. div.button-group.filter.actions)
    # from beating actual content cards (e.g. article.product-row).
    CONTENT_TAGS = {"article", "li", "tr"}
    candidates.sort(
        key=lambda x: (x[0][0] in CONTENT_TAGS, len(x[0][1]), x[1]),
        reverse=True,
    )
    best_tag, best_classes = candidates[0][0]

    # Return all elements matching the best pattern
    if best_classes:
        selector = best_tag + "".join(f".{c}" for c in sorted(best_classes))
        try:
            return soup.select(selector)[:50]  # cap at 50 events
        except Exception:
            pass

    return soup.find_all(best_tag)[:50]


def apply_links_rule(rule: ExtractionRule, html: str, base_url: str) -> list[str]:
    """
    Apply a 'links' rule to listing page HTML.
    Returns a list of absolute article URLs found.

    css_selector: selector targets <a> elements or containers holding <a> elements.
    regex: pattern must capture the URL — either as a named group 'url' or group 1.
           Example: href="(/nieuws/[^"]+)"  or  (?P<url>/agenda/[^\\s]+)
    """
    base_netloc = urlparse(base_url).netloc

    def _normalise(href: str) -> str | None:
        href = href.strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            return None
        if not href.startswith("http"):
            href = urljoin(base_url, href)
        if urlparse(href).netloc != base_netloc:
            return None
        return href

    try:
        urls = []

        if rule.rule_type == "css_selector":
            soup = BeautifulSoup(html, "lxml")
            for el in soup.select(rule.rule_definition):
                if el.name == "a":
                    href = el.get("href", "")
                else:
                    a = el.find("a", href=True)
                    href = a["href"] if a else ""
                norm = _normalise(href)
                if norm:
                    urls.append(norm)

        elif rule.rule_type == "regex":
            for m in re.finditer(rule.rule_definition, html):
                # Accept named group 'url', else group 1, else full match
                try:
                    href = m.group("url")
                except IndexError:
                    href = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
                norm = _normalise(href)
                if norm:
                    urls.append(norm)

        return list(dict.fromkeys(urls))  # deduplicate, preserve order

    except Exception as exc:
        logger.warning("Links rule %s failed: %s", rule.id, exc)
        return []


def apply_content_rule(rule: ExtractionRule, html: str) -> str | None:
    """Apply a 'content' rule to article HTML. Returns extracted text or None."""
    try:
        if rule.rule_type == "css_selector":
            soup = BeautifulSoup(html, "lxml")
            elements = soup.select(rule.rule_definition)
            return "\n\n".join(el.get_text(separator=" ", strip=True) for el in elements) or None
        elif rule.rule_type == "regex":
            matches = re.findall(rule.rule_definition, html, re.DOTALL)
            if matches:
                soup = BeautifulSoup(" ".join(matches), "lxml")
                return soup.get_text(separator=" ", strip=True)
    except Exception as exc:
        logger.warning("Content rule %s failed: %s", rule.id, exc)
    return None


def apply_events_rule(rule: ExtractionRule, html: str) -> list:
    """
    Apply an 'events' rule (CSS selector) to listing page HTML.
    Returns a list of BeautifulSoup elements — one per event container.
    """
    try:
        if rule.rule_type == "css_selector":
            soup = BeautifulSoup(html, "lxml")
            return soup.select(rule.rule_definition)
    except Exception as exc:
        logger.warning("Events rule %s failed: %s", rule.id, exc)
    return []


def get_listing_html(source: Source) -> str | None:
    """Fetch the source listing/homepage HTML (for links rule generation + preview)."""
    return _fetch_html(source.base_url, source)


def get_article_sample_html(source: Source) -> str | None:
    """
    Return HTML of a real article page for content rule generation/preview.
    Priority: cached article > links rule + fetch > heuristic crawl.
    For article_page sources, return the base_url HTML directly.
    """
    # article_page: the URL itself is the article
    if source.type == "article_page":
        return _fetch_html(source.base_url, source)

    # 1. Already cached from a previously extracted article
    cached = get_cached_article_html(source)
    if cached:
        return cached

    # 2. Use approved links rule to find an article URL
    links_rules = _active_rules(source, purpose="links")
    if links_rules:
        listing_html = _fetch_html(source.base_url, source)
        if listing_html:
            urls = apply_links_rule(links_rules[0], listing_html, source.base_url)
            for url in urls[:5]:
                html = _fetch_html(url, source)
                if html:
                    logger.info("Fetched article sample via links rule: %s", url)
                    return html

    # 3. Heuristic: find first plausible article link on homepage
    return _heuristic_article_sample(source)


def get_cached_article_html(source: Source) -> str | None:
    """Return cached HTML for any article belonging to this source (full, untruncated)."""
    rendered = bool(getattr(source, "render_js", False))
    articles = Article.query.filter_by(source_id=source.id).limit(5).all()
    for article in articles:
        html = _read_cache(article.url, rendered=rendered)
        if html is not None:
            return html
    return None


# ── Geo verification ──────────────────────────────────────────────────────────

def _verify_geo_scope(geo_scope: str, title: str, text: str, geo_ctx: dict) -> str:
    """
    Cross-check the LLM's geo_scope against keyword presence in the article text.
    If the LLM claims "local" but the town name isn't in the content, demote it
    to the most specific scope that IS supported by the text.
    Only applied to non-trusted sources.
    """
    haystack = (title + " " + text[:2000]).lower()

    town = geo_ctx.get("town", "").lower()
    region_towns = [t.lower() for t in (geo_ctx.get("region_towns") or [])]
    province_towns = [t.lower() for t in (geo_ctx.get("province_towns") or [])]

    if geo_scope == "local":
        if town and town in haystack:
            return "local"
        # Town not found — demote based on what IS present
        if any(t in haystack for t in region_towns):
            return "region"
        if any(t in haystack for t in province_towns):
            return "province"
        return "region"   # conservative fallback for regional sources

    return geo_scope


# ── Topic helpers ─────────────────────────────────────────────────────────────

def _apply_topic_labels(article: Article, topic_labels: list[str]) -> None:
    """
    Match LLM-suggested topic labels against existing Topics (case-insensitive).
    Assign matched ones to the article; queue unmatched ones as SuggestedTopics.
    Falls back to 'Overig' if nothing matched and that topic exists.
    """
    existing = {t.name.lower(): t for t in Topic.query.all()}

    if not topic_labels:
        overig = existing.get("overig")
        if overig and overig not in article.topics:
            article.topics.append(overig)
        return

    for label in topic_labels:
        label_lower = label.lower()
        if label_lower in existing:
            topic = existing[label_lower]
            if topic not in article.topics:
                article.topics.append(topic)
        else:
            suggestion = SuggestedTopic.query.filter(
                db.func.lower(SuggestedTopic.name) == label_lower
            ).first()
            if suggestion is None:
                suggestion = SuggestedTopic(name=label, article_count=0)
                db.session.add(suggestion)
                db.session.flush()
            if article not in suggestion.articles:
                suggestion.articles.append(article)
                suggestion.article_count += 1


# ── Internal helpers ──────────────────────────────────────────────────────────

def _active_rules(source: Source, purpose: str) -> list[ExtractionRule]:
    return (
        ExtractionRule.query
        .filter_by(source_id=source.id, approved=True, rule_purpose=purpose)
        .order_by(ExtractionRule.created_at.desc())
        .all()
    )


def _fetch_html(url: str, source: Source | None = None) -> str | None:
    """Fetch HTML, using Playwright when source.render_js is True. Cache-aware."""
    return _browser_get_html(url, source)


def _heuristic_links_rule(soup: "BeautifulSoup", base_url: str) -> dict | None:
    """
    Find a CSS selector that targets article links on a listing page.
    Strategy:
    1. Collect all internal <a> elements with path depth >= 2.
    2. Group by parent's (tag, class-tuple); the largest group is likely the article list.
    3. Derive selector from parent class or, fallback, from URL path prefix.
    """
    from collections import Counter

    base_netloc = urlparse(base_url).netloc

    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        if not href.startswith("http"):
            href = urljoin(base_url, href)
        parsed = urlparse(href)
        if parsed.netloc != base_netloc:
            continue
        segments = [s for s in parsed.path.strip("/").split("/") if s]
        if len(segments) < 2:
            continue
        candidates.append((a, parsed.path))

    if not candidates:
        return None

    # Group by parent element's (tag, first class)
    parent_counter: Counter = Counter()
    for a, path in candidates:
        parent = a.parent
        if parent is None:
            continue
        classes = parent.get("class") or []
        key = (parent.name, classes[0] if classes else "")
        parent_counter[key] += 1

    (top_tag, top_cls), top_count = parent_counter.most_common(1)[0]
    if top_count >= 3 and top_cls:
        # Build selector: parent.class > a  (or just parent.class a)
        sel = f"{top_tag}.{top_cls} a"
        # Verify it actually selects something meaningful
        try:
            found = soup.select(sel)
            if len(found) >= 3:
                return {"rule_type": "css_selector", "rule_definition": sel}
        except Exception:
            pass

    # Fallback: most common first path segment → a[href*='/segment/']
    first_segs: Counter = Counter()
    for a, path in candidates:
        segs = [s for s in path.strip("/").split("/") if s]
        if segs:
            first_segs[segs[0]] += 1

    if first_segs:
        top_seg, seg_count = first_segs.most_common(1)[0]
        if seg_count >= 3:
            return {"rule_type": "css_selector", "rule_definition": f"a[href*='/{top_seg}/']"}

    return None


def _heuristic_content_rule(soup: "BeautifulSoup") -> dict | None:
    """
    Find a CSS selector for the main article body on an article page.

    Unlike links/events rules (which look for repeating patterns), article
    pages contain a SINGLE main prose block.  We identify it by:
    1. Fast-path: try well-known class names used by common CMS platforms.
    2. Scoring: rank every block element by paragraph density, penalise
       link-heavy elements (nav / tag clouds) and very shallow elements
       (body, wrappers that contain the entire page).  The highest-scoring
       element with ≥ 2 <p> children is the content block.
    """
    COMMON_SELECTORS = [
        "article .article__content", "article .article__body",
        ".article__content", ".article__body",
        ".article-content", ".article-body",
        ".post-content", ".entry-content",
        ".news-detail__body", ".news-content",
        ".article-detail__body", ".article-text",
        ".nieuws-tekst", ".bericht-inhoud",
        "article", ".content-body", ".main-content article",
    ]
    for sel in COMMON_SELECTORS:
        try:
            els = soup.select(sel)
            if not els:
                continue
            text = " ".join(el.get_text(" ", strip=True) for el in els)
            # Must have real prose: substantial text AND at least 2 paragraphs
            p_count = sum(len(el.find_all("p")) for el in els)
            if len(text) > 300 and p_count >= 2:
                return {"rule_type": "css_selector", "rule_definition": sel}
        except Exception:
            continue

    # Scoring fallback — find the single densest prose block
    SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside",
                 "noscript", "form", "figure", "figcaption"}

    candidates = []
    for el in soup.find_all(["div", "section", "article", "main"]):
        if el.name in SKIP_TAGS:
            continue
        if any(p.name in SKIP_TAGS for p in el.parents):
            continue

        p_tags = el.find_all("p", recursive=True)
        p_count = len(p_tags)
        if p_count < 2:          # need at least 2 paragraphs
            continue

        text = el.get_text(" ", strip=True)
        text_len = len(text)
        if text_len < 200:
            continue

        # Penalise link-heavy elements (menus, tag clouds, related-article lists)
        link_count = len(el.find_all("a"))
        if link_count > p_count * 3:
            continue             # more than 3 links per paragraph ≈ navigation

        # Paragraphs are the primary signal; depth breaks ties (prefer specific nodes)
        depth = len(list(el.parents))
        score = p_count * 600 + text_len + depth * 30

        # Prefer elements whose identifier is class/id (more robust selectors)
        has_class = bool(el.get("class"))
        has_id    = bool(el.get("id"))
        if has_class or has_id:
            score += 200

        candidates.append((score, el))

    if not candidates:
        return None

    candidates.sort(key=lambda x: -x[0])
    best_el = candidates[0][1]

    classes = best_el.get("class") or []
    eid = best_el.get("id")
    if classes:
        sel = best_el.name + "." + ".".join(classes[:2])
    elif eid:
        sel = f"#{eid}"
    else:
        sel = best_el.name
    return {"rule_type": "css_selector", "rule_definition": sel}


def _heuristic_events_rule(soup: "BeautifulSoup") -> dict | None:
    """Reuse the existing repeating-pattern heuristic and convert to a selector."""
    elements = _find_repeating_event_containers(soup)
    if not elements:
        return None
    el = elements[0]
    classes = el.get("class") or []
    if classes:
        sel = el.name + "." + ".".join(classes[:2])
        return {"rule_type": "css_selector", "rule_definition": sel}
    return None


def _heuristic_article_sample(source: Source) -> str | None:
    """Last resort: crawl homepage and pick the first link that looks like an article."""
    homepage_html = _fetch_html(source.base_url, source)
    if not homepage_html:
        return None

    soup = BeautifulSoup(homepage_html, "lxml")
    base_p = urlparse(source.base_url)

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            href = urljoin(source.base_url, href)
        p = urlparse(href)
        if p.netloc != base_p.netloc:
            continue
        # Must have at least 2 path segments (e.g. /nieuws/artikel-slug)
        segments = [s for s in p.path.strip("/").split("/") if s]
        if len(segments) < 2:
            continue
        title = a.get_text(strip=True)
        if len(title) < 15:
            continue
        html = _fetch_html(href, source)
        if html:
            logger.info("Heuristic article sample: %s", href)
            return html[:10000]

    logger.warning("Could not find article sample for %s", source.base_url)
    return None
