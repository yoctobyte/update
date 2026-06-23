#!/usr/bin/env python3
"""
histsearch — historical article search and archival tool

Usage:
  python histsearch.py topic set "Wageningen"
  python histsearch.py topic show
  python histsearch.py search "Wageningen WWII"
  python histsearch.py search "Wageningen bevrijding 1945" --engines bing
  python histsearch.py fetch [--limit 20]
  python histsearch.py domains
  python histsearch.py domains js <domain>       # enable JS for domain
  python histsearch.py articles [--status pending|approved|rejected]
  python histsearch.py articles show <id>
  python histsearch.py articles approve <id>
  python histsearch.py articles reject <id>
  python histsearch.py articles date <id> <YYYY-MM-DD>
  python histsearch.py export
  python histsearch.py stats
"""

import argparse
import json
import logging
import sys

import db
import fetcher
import searcher
import exporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Quiet noisy deps
logging.getLogger("trafilatura").setLevel(logging.WARNING)
logging.getLogger("dateparser").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


def cmd_topic(args):
    db.init()
    if args.topic_cmd == "set":
        db.set_topic(args.name)
        print(f"Active topic set to: {args.name}")
    elif args.topic_cmd == "show":
        with db.connect() as conn:
            t = db.get_active_topic(conn)
        if t:
            print(f"Active topic: {t['name']}  (id={t['id']}, since {t['created_at'][:10]})")
        else:
            print("No active topic. Set one with: python histsearch.py topic set \"<name>\"")


def cmd_search(args):
    db.init()
    with db.connect() as conn:
        topic = db.get_active_topic(conn)
    if not topic:
        print("No active topic. Run: python histsearch.py topic set \"<name>\"")
        sys.exit(1)

    engines = args.engines.split(",") if args.engines else ["bing", "ddg"]
    print(f"Searching '{args.query}' on {engines}...")

    results = searcher.search(args.query, engines=engines, max_per_engine=args.max)

    all_urls = []
    for engine, urls in results.items():
        print(f"  {engine}: {len(urls)} results")
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO search_runs(topic_id,query,engine,ran_at,result_count) VALUES(?,?,?,?,?)",
                (topic["id"], args.query, engine, db.now_iso(), len(urls)),
            )
        for url in urls:
            domain = searcher._domain(url)
            all_urls.append((url, domain, args.query))

    added = db.add_urls(topic["id"], all_urls)
    print(f"  → {added} new URLs added ({len(all_urls) - added} already known)")


def cmd_fetch(args):
    db.init()
    with db.connect() as conn:
        topic = db.get_active_topic(conn)
    if not topic:
        print("No active topic.")
        sys.exit(1)

    fetcher.fetch_pending(topic["id"], limit=args.limit, delay=args.delay)


def cmd_domains(args):
    db.init()
    domains = db.get_domains()
    if not domains:
        print("No domains recorded yet.")
        return

    if hasattr(args, "domain_cmd") and args.domain_cmd == "js":
        db.upsert_domain(args.domain, js_enabled=1)
        print(f"JS enabled for: {args.domain}")
        return

    print(f"{'Domain':<40} {'URLs':>6} {'JS?':>5} {'Enabled':>8} {'Blocked':>8}")
    print("-" * 75)
    for d in domains:
        print(
            f"{d['domain']:<40} {d['url_count']:>6} "
            f"{'yes' if d['js_required'] else '-':>5} "
            f"{'yes' if d['js_enabled'] else '-':>8} "
            f"{'yes' if d['blocked'] else '-':>8}"
        )


def cmd_articles(args):
    db.init()

    if hasattr(args, "article_cmd"):
        if args.article_cmd == "show":
            a = db.get_article(args.id)
            if not a:
                print(f"Article {args.id} not found.")
                return
            print(f"\n{'='*70}")
            print(f"ID:       {a['id']}")
            print(f"URL:      {a['url']}")
            print(f"Domain:   {a['domain']}")
            print(f"Title:    {a['title']}")
            print(f"Date:     {a['date_selected']} (selected)")
            cands = json.loads(a["date_candidates"] or "[]")
            if cands:
                print(f"Dates:    {', '.join(cands)}")
            print(f"Internet: {a['date_internet']}")
            print(f"Historic: {a['date_historical']}")
            print(f"Status:   {a['review_status']}")
            if a["prompt_injection_flag"]:
                print(f"⚠ INJECTION FLAG: {a['prompt_injection_notes']}")
            print(f"\n--- TEXT ({len(a['extracted_text'] or '')} chars) ---")
            text = (a["extracted_text"] or "")
            print(text[:2000])
            if len(text) > 2000:
                print(f"... [{len(text)-2000} more chars]")
            print()
            return

        elif args.article_cmd == "approve":
            db.set_article_status(args.id, "approved")
            print(f"Article {args.id} approved.")
            return

        elif args.article_cmd == "reject":
            db.set_article_status(args.id, "rejected")
            print(f"Article {args.id} rejected.")
            return

        elif args.article_cmd == "date":
            db.set_article_date(args.id, args.date)
            print(f"Article {args.id} date set to {args.date}.")
            return

    # Default: list
    status = getattr(args, "status", "pending") or "pending"
    rows = db.get_articles(status=status, limit=args.limit, offset=args.offset)
    if not rows:
        print(f"No {status} articles.")
        return

    print(f"\n{'ID':>6}  {'Date':^12}  {'Inj':^3}  {'Domain':<30}  Title")
    print("-" * 100)
    for a in rows:
        inj = "⚠" if a["prompt_injection_flag"] else " "
        date = (a["date_selected"] or "?")[:10]
        title = (a["title"] or "")[:50]
        print(f"{a['id']:>6}  {date:^12}  {inj:^3}  {a['domain']:<30}  {title}")
    print(f"\n{len(rows)} articles shown (status={status})")


def cmd_export(args):
    db.init()
    with db.connect() as conn:
        topic = db.get_active_topic(conn)
    if not topic:
        print("No active topic.")
        sys.exit(1)
    exporter.export_articles(topic["id"], status=args.status)


def cmd_stats(args):
    db.init()
    with db.connect() as conn:
        topic = db.get_active_topic(conn)
    if not topic:
        print("No active topic.")
        return

    s = db.stats(topic["id"])
    print(f"\nTopic: {topic['name']}")
    print(f"Search runs: {s['search_runs']}")
    print("\nURLs:")
    for status, n in sorted(s["urls"].items()):
        print(f"  {status:<15} {n}")
    print("\nArticles:")
    for status, n in sorted(s["articles"].items()):
        print(f"  {status:<15} {n}")
    print()


def main():
    db.init()

    p = argparse.ArgumentParser(prog="histsearch", description="Historical article search tool")
    sub = p.add_subparsers(dest="cmd")

    # topic
    t = sub.add_parser("topic", help="Manage active topic")
    ts = t.add_subparsers(dest="topic_cmd")
    ts_set = ts.add_parser("set")
    ts_set.add_argument("name")
    ts.add_parser("show")

    # search
    s = sub.add_parser("search", help="Search engines and collect URLs")
    s.add_argument("query")
    s.add_argument("--engines", default="bing,ddg", help="Comma-separated: bing,ddg")
    s.add_argument("--max", type=int, default=50, help="Max results per engine")

    # fetch
    f = sub.add_parser("fetch", help="Fetch and extract pending URLs")
    f.add_argument("--limit", type=int, default=20)
    f.add_argument("--delay", type=float, default=1.5, help="Seconds between requests")

    # domains
    d = sub.add_parser("domains", help="List/manage domains")
    ds = d.add_subparsers(dest="domain_cmd")
    ds_js = ds.add_parser("js", help="Enable JS for a domain")
    ds_js.add_argument("domain")

    # articles
    a = sub.add_parser("articles", help="Review extracted articles")
    a.add_argument("--status", default="pending", choices=["pending", "approved", "rejected"])
    a.add_argument("--limit", type=int, default=50)
    a.add_argument("--offset", type=int, default=0)
    as_ = a.add_subparsers(dest="article_cmd")
    show_p = as_.add_parser("show")
    show_p.add_argument("id", type=int)
    ap = as_.add_parser("approve")
    ap.add_argument("id", type=int)
    rj = as_.add_parser("reject")
    rj.add_argument("id", type=int)
    dt = as_.add_parser("date", help="Override date for article")
    dt.add_argument("id", type=int)
    dt.add_argument("date", help="YYYY-MM-DD")

    # export
    ex = sub.add_parser("export", help="Export approved articles to output/")
    ex.add_argument("--status", default="approved", choices=["approved", "pending"])

    # stats
    sub.add_parser("stats", help="Show pipeline statistics")

    args = p.parse_args()

    dispatch = {
        "topic": cmd_topic,
        "search": cmd_search,
        "fetch": cmd_fetch,
        "domains": cmd_domains,
        "articles": cmd_articles,
        "export": cmd_export,
        "stats": cmd_stats,
    }

    if args.cmd in dispatch:
        dispatch[args.cmd](args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
