"""Export approved articles to output folders as JSON files."""
import json
import re
from pathlib import Path

import db

OUTPUT_DIR = Path(__file__).parent / "output"


def slugify(text: str) -> str:
    text = (text or "untitled")[:60]
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-")


def export_articles(topic_id: int, status: str = "approved") -> int:
    rows = db.get_articles(status=status, limit=9999)
    if not rows:
        print(f"No {status} articles to export.")
        return 0

    # Get topic name for folder
    with db.connect() as conn:
        topic = conn.execute("SELECT name FROM topics WHERE id=?", (topic_id,)).fetchone()
    topic_slug = slugify(topic["name"] if topic else "unknown")

    out_dir = OUTPUT_DIR / topic_slug / status
    out_dir.mkdir(parents=True, exist_ok=True)

    exported = 0
    for row in rows:
        fname = f"{row['id']:05d}_{slugify(row['title'] or 'untitled')}.json"
        payload = {
            "id": row["id"],
            "url": row["url"],
            "domain": row["domain"],
            "title": row["title"],
            "text": row["extracted_text"],
            "date_selected": row["date_selected"],
            "date_internet": row["date_internet"],
            "date_historical": row["date_historical"],
            "date_candidates": json.loads(row["date_candidates"] or "[]"),
            "prompt_injection_flag": bool(row["prompt_injection_flag"]),
            "review_status": row["review_status"],
        }
        (out_dir / fname).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        exported += 1

    print(f"Exported {exported} articles to {out_dir}")
    return exported
