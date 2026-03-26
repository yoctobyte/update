"""
Shared HTML-fetching helpers used by both fetcher and extractor.

Provides a single _get_html(url, source) entry point that:
  1. Checks the disk cache first (keyed by URL MD5)
  2. Fetches via Playwright if source.render_js is True
  3. Falls back to plain requests otherwise
  4. Writes the result back to the disk cache

This module holds _render_with_playwright so neither fetcher nor extractor
needs to import the other (avoiding circular imports).
"""
import hashlib
import logging

import requests

from ..config import Config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
REQUEST_HEADERS = {"User-Agent": "LokaalNieuws/1.0 (local news aggregator)"}


# ── Disk cache ────────────────────────────────────────────────────────────────

def _cache_path(url: str, rendered: bool = False):
    suffix = "|js" if rendered else ""
    fname = hashlib.md5((url + suffix).encode()).hexdigest() + ".html"
    return Config.town_cache_path() / fname


def read_cache(url: str, rendered: bool = False) -> str | None:
    try:
        p = _cache_path(url, rendered)
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass
    return None


def write_cache(url: str, html: str, rendered: bool = False) -> None:
    try:
        p = _cache_path(url, rendered)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not cache %s: %s", url, exc)


# ── Playwright ────────────────────────────────────────────────────────────────

def render_with_playwright(url: str, cookie_accept_selector: str | None = None) -> str:
    """
    Render a URL with headless Chromium via Playwright.
    Optionally clicks a CSS selector to dismiss cookie/consent walls.
    Raises RuntimeError if Playwright is not installed.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        raise RuntimeError(
            "Playwright is not installed. Run: "
            "pip install playwright && playwright install chromium"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                user_agent=REQUEST_HEADERS["User-Agent"],
                extra_http_headers={"Accept-Language": "nl-NL,nl;q=0.9"},
            )
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)

            # Best-effort: wait for AJAX/XHR to finish so dynamically loaded
            # content (e.g. article lists fetched after DOMContentLoaded) is present.
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except PWTimeout:
                pass  # Proceed with whatever loaded so far

            if cookie_accept_selector:
                try:
                    page.click(cookie_accept_selector, timeout=5_000)
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except PWTimeout:
                    logger.debug(
                        "Cookie selector '%s' timed out — continuing without clicking",
                        cookie_accept_selector,
                    )
                except Exception as exc:
                    logger.debug("Cookie accept click failed: %s", exc)

            return page.content()
        finally:
            browser.close()


# ── Main entry point ──────────────────────────────────────────────────────────

def get_html(url: str, source=None, skip_cache: bool = False) -> str | None:
    """
    Fetch HTML for a URL.

    - Checks disk cache first (unless skip_cache=True)
    - If source.render_js: fetches via Playwright (with optional consent selector)
    - Otherwise: plain requests
    - Writes result to cache

    source may be None for anonymous fetches (always uses plain requests).
    """
    render_js = source is not None and getattr(source, "render_js", False)

    if not skip_cache:
        cached = read_cache(url, rendered=render_js)
        if cached is not None:
            logger.debug("Cache hit: %s (render_js=%s)", url, render_js)
            return cached

    try:
        if render_js:
            logger.debug("Fetching %s with Playwright (render_js)", url)
            html = render_with_playwright(
                url,
                getattr(source, "cookie_accept_selector", None) or None,
            )
        else:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        logger.warning("Could not fetch %s: %s", url, exc)
        return None

    write_cache(url, html, rendered=render_js)
    return html


def conditional_fetch(url: str, source) -> tuple[str | None, bool]:
    """
    Fetch a URL using HTTP conditional GET for non-JS sources.

    Sends If-None-Match / If-Modified-Since headers based on values stored
    on the source object.  On 304 the disk-cached HTML is returned unchanged.
    On 200 the new HTML is written to the disk cache and the source object's
    http_etag / http_last_modified are updated (caller must commit).

    Returns (html, changed):
      - html:    page HTML (or None on error)
      - changed: True if the server returned a fresh 200, False on 304 / no change

    For render_js sources falls back to a normal unconditional Playwright fetch.
    """
    render_js = getattr(source, "render_js", False)

    if render_js:
        html = render_with_playwright(
            url,
            getattr(source, "cookie_accept_selector", None) or None,
        )
        if html is None:
            return None, False
        write_cache(url, html, rendered=True)
        return html, True  # can't detect 304 via Playwright

    headers = dict(REQUEST_HEADERS)
    etag = getattr(source, "http_etag", None)
    last_modified = getattr(source, "http_last_modified", None)
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
    except Exception as exc:
        logger.warning("Could not fetch %s: %s", url, exc)
        return None, False

    if resp.status_code == 304:
        logger.debug("304 Not Modified: %s — using cached HTML", url)
        cached = read_cache(url, rendered=False)
        return cached, False

    try:
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("HTTP error fetching %s: %s", url, exc)
        return None, False

    html = resp.text
    write_cache(url, html, rendered=False)

    # Update conditional GET tokens on the source (caller must db.session.commit)
    new_etag = resp.headers.get("ETag")
    new_lm = resp.headers.get("Last-Modified")
    if new_etag is not None:
        source.http_etag = new_etag
    if new_lm is not None:
        source.http_last_modified = new_lm

    return html, True
