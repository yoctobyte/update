"""Fetch and snapshot watched URLs without any parsing."""
import gzip
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from ..config import Config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20
REQUEST_HEADERS = {"User-Agent": "LokaalNieuws/1.0 (local news aggregator)"}

RSS_CONTENT_TYPES = {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}


def _snapshot_dir(url: str) -> Path:
    key = hashlib.md5(url.encode()).hexdigest()
    return Config.town_cache_path().parent / "snapshots" / key


def snapshot_count(url: str) -> int:
    d = _snapshot_dir(url)
    if not d.exists():
        return 0
    return len(list(d.glob("*.gz")))


def fetch_watched_url(entry) -> bool:
    """
    Fetch a WatchedURL and save a gzip-compressed timestamped snapshot.
    - Uses Playwright if entry.render_js is True.
    - Auto-detects RSS on first fetch and sets interval to 1 hour.
    Returns True on success.
    """
    html: str | None = None

    if entry.render_js:
        try:
            from .browser import render_with_playwright
            html = render_with_playwright(entry.url)
        except Exception as exc:
            logger.warning("Watcher: Playwright failed for %s: %s", entry.url, exc)
            return False
    else:
        try:
            resp = requests.get(entry.url, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
            resp.raise_for_status()
            html = resp.text

            # Auto-detect RSS on first fetch
            if entry.is_rss is None:
                ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                entry.is_rss = ct in RSS_CONTENT_TYPES
                if entry.is_rss:
                    entry.fetch_interval_hours = 1
                    logger.debug("Watcher: detected RSS for %s — interval set to 1h", entry.url)
        except Exception as exc:
            logger.warning("Watcher: could not fetch %s: %s", entry.url, exc)
            return False

    snap_dir = _snapshot_dir(entry.url)
    snap_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    snap_path = snap_dir / f"{ts}.gz"
    snap_path.write_bytes(gzip.compress(html.encode("utf-8")))
    logger.debug("Watcher: snapshot saved for %s (%s, %d bytes)", entry.url, ts, snap_path.stat().st_size)
    return True


def fetch_all_watched(app) -> None:
    """Fetch watched URLs that are due. Called from scheduler (runs every 30 min)."""
    from ..extensions import db
    from ..models import WatchedURL

    with app.app_context():
        now = datetime.now(timezone.utc)
        entries = WatchedURL.query.filter_by(active=True).all()
        fetched = 0
        for entry in entries:
            due = (
                entry.last_fetched_at is None
                or (now - entry.last_fetched_at) >= timedelta(hours=entry.fetch_interval_hours)
            )
            if not due:
                continue
            ok = fetch_watched_url(entry)
            if ok:
                entry.last_fetched_at = now
                entry.consecutive_failures = 0
                fetched += 1
            else:
                entry.consecutive_failures = (entry.consecutive_failures or 0) + 1
                if entry.consecutive_failures >= 10:
                    entry.active = False
                    logger.warning(
                        "Watcher: deactivating %s after %d consecutive failures",
                        entry.url, entry.consecutive_failures,
                    )
        db.session.commit()
        logger.info("Watcher: fetched %d/%d URLs", fetched, len(entries))
