#!/usr/bin/env python3
"""
Import uncommented RSS feeds from rss_feeds_import.txt into the database as Source records.

Usage:
  python import_rss_sources.py                  # import as inactive (admin must enable)
  python import_rss_sources.py --enable         # import and immediately activate
  python import_rss_sources.py --file other.txt # use a different input file
  python import_rss_sources.py --dry-run        # show what would be imported without writing

Format of input file (lines starting with # are skipped):
  publisher | title | url
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# Bootstrap Flask app context
sys.path.insert(0, str(Path(__file__).parent))
from app import create_app
from app.extensions import db
from app.models.source import Source

INPUT = Path(__file__).parent / "rss_feeds_import.txt"


def parse_args():
    p = argparse.ArgumentParser(description="Import RSS feeds into the lokaalnieuws database")
    p.add_argument("--enable", action="store_true", help="Activate imported sources immediately")
    p.add_argument("--file", type=Path, default=INPUT, help="Input file (default: rss_feeds_import.txt)")
    p.add_argument("--dry-run", action="store_true", help="Print what would be imported without writing")
    return p.parse_args()


def load_entries(path: Path) -> list[tuple[str, str, str]]:
    entries = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("publisher"):
            continue
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) != 3:
            print(f"  [WARN] Line {lineno}: malformed, skipping: {line!r}")
            continue
        publisher, title, url = parts
        if not url.startswith("http"):
            print(f"  [WARN] Line {lineno}: invalid URL, skipping: {url!r}")
            continue
        entries.append((publisher, title, url))
    return entries


def base_url_from(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def main():
    args = parse_args()

    entries = load_entries(args.file)
    if not entries:
        print("No uncommented entries found. Edit rss_feeds_import.txt and remove # from desired lines.")
        sys.exit(0)

    print(f"Found {len(entries)} entries to import (active={'yes' if args.enable else 'no'}).")
    if args.dry_run:
        print("\nDry run — nothing will be written:\n")
        for publisher, title, url in entries:
            print(f"  {publisher} | {title} | {url}")
        sys.exit(0)

    os.environ["TESTING"] = "1"  # prevents scheduler from starting inside create_app
    app = create_app()
    with app.app_context():
        added = skipped = 0
        for publisher, title, url in entries:
            existing = Source.query.filter_by(base_url=url).first()
            if existing:
                print(f"  [SKIP] Already exists: {url}")
                skipped += 1
                continue

            source = Source(
                name=f"{publisher} — {title}",
                base_url=url,
                type="rss",
                active=args.enable,
                filter_scope="none",
            )
            db.session.add(source)
            status = "ACTIVE" if args.enable else "inactive"
            print(f"  [ADD {status}] {source.name}")
            added += 1

        db.session.commit()
        print(f"\nDone. Added: {added}, skipped (already exist): {skipped}.")


if __name__ == "__main__":
    main()
