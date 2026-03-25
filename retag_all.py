#!/usr/bin/env python3
"""
Clear all article–topic associations and re-queue articles for tagging.
The scheduler's tag_untagged_articles job will pick them up automatically.

Usage:
    TOWN=wageningen python3 retag_all.py
    TOWN=wageningen python3 retag_all.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ["TESTING"] = "1"

from app import create_app
from app.extensions import db
from app.models.article import Article
from app.models.associations import article_topics  # the join table


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    app = create_app()
    with app.app_context():
        count = db.session.execute(
            db.select(db.func.count()).select_from(article_topics)
        ).scalar()
        print(f"Current article–topic associations: {count}")

        if args.dry_run:
            print("Dry run — nothing changed.")
            return

        db.session.execute(article_topics.delete())
        db.session.commit()
        print(f"Cleared {count} associations. Scheduler will retag on next run.")


if __name__ == "__main__":
    main()
