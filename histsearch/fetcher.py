"""Fetch URLs and extract content."""
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

import db
import extractor

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

RAW_HTML_DIR = Path(__file__).parent / "output" / "raw_html"


def _save_raw(url_id: int, html: str) -> str:
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_HTML_DIR / f"{url_id}.html"
    path.write_text(html, encoding="utf-8", errors="replace")
    return str(path)


def fetch_with_js(url: str) -> str | None:
    """Fetch using Playwright (Chromium). Returns HTML or None."""
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except PWTimeout:
                pass
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        logger.warning("JS fetch failed for %s: %s", url, exc)
        return None


def fetch_url(url_row) -> None:
    """Fetch one URL row, extract, and save to DB."""
    url_id = url_row["id"]
    url = url_row["url"]
    js_enabled = url_row["js_enabled"]

    logger.info("Fetching [%d] %s", url_id, url)

    html = None
    try:
        if js_enabled:
            html = fetch_with_js(url)
        else:
            r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
            r.raise_for_status()
            html = r.text
    except Exception as exc:
        logger.warning("  Failed: %s", exc)
        db.mark_url(url_id, "failed", fail=True)
        return

    if not html:
        db.mark_url(url_id, "failed", fail=True)
        return

    raw_path = _save_raw(url_id, html)
    data = extractor.extract(html, url)
    data["raw_html_path"] = raw_path

    if data.get("js_required") and not js_enabled:
        logger.info("  → JS required, flagging domain")
        db.mark_url(url_id, "js_required")
        domain = url_row["domain"]
        db.upsert_domain(domain, js_required=1)
        return

    if not data.get("text"):
        logger.info("  → No text extracted")
        db.mark_url(url_id, "failed", fail=True)
        return

    db.save_article(url_id, url, data)
    db.mark_url(url_id, "fetched")

    inj = "⚠ INJECTION FLAG" if data.get("injection_flag") else ""
    logger.info(
        "  ✓ '%s' | date=%s | %d chars %s",
        (data.get("title") or "")[:60],
        data.get("date_selected", "?"),
        len(data.get("text") or ""),
        inj,
    )


def fetch_pending(topic_id: int, limit: int = 20, delay: float = 1.5) -> int:
    rows = db.get_pending_urls(topic_id, limit=limit)
    if not rows:
        print("No pending URLs.")
        return 0

    print(f"Fetching {len(rows)} URLs...")
    done = 0
    for row in rows:
        fetch_url(row)
        done += 1
        time.sleep(delay)

    return done
