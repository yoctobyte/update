"""Extract article text, title, and dates from HTML."""
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Prompt injection detection ────────────────────────────────────────────────

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior|above)",
    r"forget\s+(everything|all previous)",
    r"you\s+are\s+now\s+(a|an|the)\s+\w+",
    r"new\s+(persona|identity|role|instructions)",
    r"act\s+as\s+(if\s+you\s+are|a|an)",
    r"system\s*prompt\s*:",
    r"<\s*system\s*>",
    r"\[INST\]",
    r"###\s*instruction",
    r"jailbreak",
    r"do\s+anything\s+now",
    r"pretend\s+(you\s+are|to\s+be)",
    r"override\s+(your\s+)?(safety|guidelines|instructions)",
]

_INJECTION_RE = re.compile(
    "|".join(_INJECTION_PATTERNS),
    re.IGNORECASE | re.MULTILINE,
)


def check_injection(text: str) -> tuple[bool, str]:
    """Return (flagged, notes). Notes lists matched patterns."""
    matches = _INJECTION_RE.findall(text or "")
    if matches:
        notes = "; ".join(str(m) for m in matches[:5])
        return True, notes
    return False, ""


# ── Date extraction ───────────────────────────────────────────────────────────

def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        import dateparser
        return dateparser.parse(s, settings={"RETURN_AS_TIMEZONE_AWARE": False, "PREFER_DAY_OF_MONTH": "first"})
    except Exception:
        return None


def _fmt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    # Clamp obviously wrong futures (e.g. year > current+1)
    if dt.year > datetime.now().year + 1:
        return None
    return dt.isoformat()


def extract_dates(soup, url: str) -> dict:
    """
    Extract all candidate dates from the page. Returns:
      date_internet   — when published on the web (meta tags etc.)
      date_historical — actual event date if different (schema.org Event, etc.)
      date_candidates — list of all ISO dates found
      date_selected   — best pick (oldest candidate)
    """
    candidates = []

    # 1. Structured data: JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0]
            for key in ("datePublished", "dateCreated", "dateModified", "startDate"):
                val = data.get(key)
                if val:
                    dt = _parse_date(str(val))
                    if dt:
                        candidates.append((_fmt(dt), key))
        except Exception:
            pass

    # 2. Meta tags
    meta_props = [
        ("property", "article:published_time"),
        ("property", "og:article:published_time"),
        ("name", "pubdate"),
        ("name", "date"),
        ("name", "DC.date"),
        ("name", "DC.Date"),
        ("itemprop", "datePublished"),
        ("itemprop", "dateCreated"),
    ]
    for attr, val in meta_props:
        tag = soup.find("meta", {attr: val})
        if tag and tag.get("content"):
            dt = _parse_date(tag["content"])
            if dt:
                candidates.append((_fmt(dt), f"meta:{val}"))

    # 3. <time> elements
    for t in soup.find_all("time"):
        raw = t.get("datetime") or t.get_text(strip=True)
        dt = _parse_date(raw)
        if dt:
            candidates.append((_fmt(dt), "time_element"))

    # 4. URL date patterns (e.g. /2024/03/15/ or /20240315)
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            candidates.append((_fmt(dt), "url_pattern"))
        except ValueError:
            pass

    # Deduplicate and sort
    seen = set()
    unique = []
    for iso, source in candidates:
        if iso and iso not in seen:
            seen.add(iso)
            unique.append((iso, source))
    unique.sort(key=lambda x: x[0])  # oldest first

    internet_date = next((iso for iso, src in unique if "pubdate" in src or "published" in src.lower() or "meta" in src), None)
    historical_date = next((iso for iso, src in unique if "startDate" in src or "Event" in src), None)
    selected = unique[0][0] if unique else None  # oldest candidate

    return {
        "date_internet": internet_date or selected,
        "date_historical": historical_date,
        "date_candidates": [iso for iso, _ in unique],
        "date_selected": selected,
    }


# ── Text extraction ───────────────────────────────────────────────────────────

_JS_SIGNATURES = [
    "__NEXT_DATA__", "__NUXT__", "window.__REDUX",
    "ng-version=", "data-reactroot", "vue-app",
    "var gatsby", "_GATSBY",
]

_MIN_TEXT_LENGTH = 150  # below this, assume JS page or no content


def is_js_required(html: str, text: str) -> bool:
    if len(text.strip()) < _MIN_TEXT_LENGTH:
        return True
    for sig in _JS_SIGNATURES:
        if sig in html:
            return True
    return False


def extract(html: str, url: str) -> dict:
    """
    Full extraction pipeline: text, title, dates, injection check.
    Returns a dict ready for db.save_article().
    """
    from bs4 import BeautifulSoup
    import trafilatura

    soup = BeautifulSoup(html, "lxml")

    # Title
    title = None
    if soup.find("meta", property="og:title"):
        title = soup.find("meta", property="og:title").get("content", "").strip()
    if not title and soup.find("h1"):
        title = soup.find("h1").get_text(strip=True)
    if not title and soup.title:
        title = soup.title.get_text(strip=True)

    # Text via trafilatura (best-in-class article extractor)
    text = trafilatura.extract(html, include_comments=False, include_tables=False)

    js_needed = is_js_required(html, text or "")

    # Dates
    dates = extract_dates(soup, url)

    # Injection check
    full_content = f"{title or ''} {text or ''}"
    inj_flag, inj_notes = check_injection(full_content)

    return {
        "title": title,
        "text": text,
        "js_required": js_needed,
        "injection_flag": inj_flag,
        "injection_notes": inj_notes if inj_flag else None,
        **dates,
    }
