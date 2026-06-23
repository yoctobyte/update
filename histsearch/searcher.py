"""Search Bing and DuckDuckGo, return list of result URLs."""
import re
import time
import logging
from urllib.parse import urlparse, urlencode, unquote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

# Domains we never want as results
SKIP_DOMAINS = {
    "google.com", "google.nl", "bing.com", "duckduckgo.com",
    "youtube.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "linkedin.com", "tiktok.com",
    "wikipedia.org",  # remove if you want wikipedia results
}


def _domain(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _is_useful(url: str) -> bool:
    d = _domain(url)
    if not d:
        return False
    if any(skip in d for skip in SKIP_DOMAINS):
        return False
    if not url.startswith("http"):
        return False
    return True


def search_bing(query: str, max_results: int = 50) -> list[str]:
    urls = []
    offset = 0
    per_page = 10

    while len(urls) < max_results:
        params = {"q": query, "first": offset + 1, "count": per_page}
        try:
            r = requests.get(
                "https://www.bing.com/search",
                params=params,
                headers=HEADERS,
                timeout=15,
            )
            r.raise_for_status()
        except Exception as exc:
            logger.warning("Bing request failed: %s", exc)
            break

        soup = BeautifulSoup(r.text, "lxml")
        found = 0
        for a in soup.select("li.b_algo h2 a, li.b_algo .b_title a"):
            href = a.get("href", "")
            if href and _is_useful(href) and href not in urls:
                urls.append(href)
                found += 1

        if found == 0:
            break  # no more results

        offset += per_page
        if offset >= max_results:
            break
        time.sleep(1.5)

    logger.info("Bing '%s': %d URLs", query, len(urls))
    return urls[:max_results]


def search_ddg(query: str, max_results: int = 50) -> list[str]:
    """DuckDuckGo HTML endpoint (no API key needed)."""
    urls = []

    try:
        r = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "nl-nl"},
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as exc:
        logger.warning("DDG request failed: %s", exc)
        return urls

    soup = BeautifulSoup(r.text, "lxml")
    for a in soup.select("a.result__a"):
        href = a.get("href", "")
        # DDG wraps URLs in redirects like //duckduckgo.com/l/?uddg=...
        if "uddg=" in href:
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                href = unquote(m.group(1))
        if href and _is_useful(href) and href not in urls:
            urls.append(href)
        if len(urls) >= max_results:
            break

    logger.info("DDG '%s': %d URLs", query, len(urls))
    return urls[:max_results]


def search(query: str, engines: list[str] = ("bing", "ddg"), max_per_engine: int = 50) -> dict[str, list[str]]:
    """Run query on requested engines. Returns {engine: [urls]}."""
    results = {}
    for engine in engines:
        if engine == "bing":
            results["bing"] = search_bing(query, max_per_engine)
        elif engine == "ddg":
            results["ddg"] = search_ddg(query, max_per_engine)
        time.sleep(2)
    return results
