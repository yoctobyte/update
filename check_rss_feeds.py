#!/usr/bin/env python3
"""
Check which RSS feeds from rss_feeds_raw.txt are alive and valid.
Writes valid feeds to rss_feeds_valid.txt.
"""

import sys
import concurrent.futures
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

INPUT  = Path(__file__).parent / "rss_feeds_raw.txt"
OUTPUT = Path(__file__).parent / "rss_feeds_valid.txt"
TIMEOUT = 10
WORKERS = 20

RSS_NAMESPACES = {"atom": "http://www.w3.org/2005/Atom"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RSS-checker/1.0)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


def is_valid_feed(content: bytes) -> bool:
    """Return True if content parses as RSS or Atom with at least one item/entry."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return False

    tag = root.tag.lower()
    # Atom: <feed>
    if "atom" in tag or tag.endswith("}feed") or tag == "feed":
        entries = root.findall(".//{http://www.w3.org/2005/Atom}entry") or root.findall(".//entry")
        return len(entries) > 0
    # RSS: <rss> or <rdf:RDF>
    if "rss" in tag or "rdf" in tag.lower():
        items = root.findall(".//item")
        return len(items) > 0
    return False


def check(entry: tuple) -> tuple | None:
    """Return (publisher, title, url) if alive and valid, else None."""
    publisher, title, url = entry
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status >= 400:
                return None
            content = resp.read(512 * 1024)  # max 512 KB
        if is_valid_feed(content):
            return (publisher, title, url)
    except Exception:
        pass
    return None


def load_entries(path: Path) -> list[tuple]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("publisher"):
            continue
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) == 3:
            entries.append(tuple(parts))
    return entries


def main():
    entries = load_entries(INPUT)
    print(f"Checking {len(entries)} feeds with {WORKERS} workers (timeout={TIMEOUT}s)...")

    valid = []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(check, e): e for e in entries}
        for fut in concurrent.futures.as_completed(futures):
            done += 1
            result = fut.result()
            entry = futures[fut]
            status = "OK " if result else "---"
            print(f"  [{done:>3}/{len(entries)}] {status}  {entry[2]}", flush=True)
            if result:
                valid.append(result)

    valid.sort(key=lambda x: (x[0].lower(), x[1].lower()))

    lines = ["publisher | title | url"]
    for publisher, title, url in valid:
        lines.append(f"{publisher} | {title} | {url}")

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nDone. {len(valid)}/{len(entries)} feeds valid → {OUTPUT}")


if __name__ == "__main__":
    main()
