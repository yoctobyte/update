#!/usr/bin/env python3
"""
logstats.py — nginx access log analyser for de.example.com

Usage:
    python3 logstats.py [logfile]

Default logfile: /var/log/nginx/de.example.com.access.log
"""

import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

LOG_RE = re.compile(
    r'(\S+)\s+'           # timestamp
    r'(\S+)\s+'           # ip
    r'"(\S+)\s+(\S+)\s+'  # method, path
    r'\S+"\s+'            # protocol
    r'(\d+)\s+'           # status
    r'(\d+)\s+'           # bytes
    r'"[^"]*"\s+'         # referer
    r'"([^"]*)"'          # user-agent
)

STATIC = re.compile(r'\.(css|js|png|ico|jpg|jpeg|svg|webp|woff2?)(\?.*)?$')

KNOWN_BOTS = re.compile(
    r'bot|crawl|spider|slurp|fetcher|archiver|scanner|checker|monitor|'
    r'python-requests|curl|wget|go-http|java|ruby|php|perl|axios|'
    r'MJ12|GPTBot|Amazonbot|Googlebot|bingbot|DuckDuckBot|Baiduspider|'
    r'YandexBot|SemrushBot|AhrefsBot|DataForSeoBot|PetalBot|Bytespider|'
    r'FacebookBot|Twitterbot|LinkedInBot|WhatsApp|Discordbot',
    re.IGNORECASE
)

SESSION_WINDOW = timedelta(seconds=30)


def parse(logfile):
    entries = []
    with open(logfile, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LOG_RE.match(line.strip())
            if not m:
                continue
            ts_str, ip, method, path, status, nbytes, ua = m.groups()
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            entries.append((ts, ip, method, path, int(status), int(nbytes), ua))
    return entries


def classify_ua(ua):
    if KNOWN_BOTS.search(ua):
        return "bot"
    return "unknown"


def analyse(entries):
    # ── Bot breakdown ─────────────────────────────────────────────────────────
    bot_counts  = defaultdict(int)   # ua -> request count
    bot_statuses = defaultdict(lambda: defaultdict(int))

    # ── Session reconstruction for organic traffic detection ─────────────────
    # Group by IP; within each IP find bursts that include both HTML and static
    ip_events = defaultdict(list)

    for ts, ip, method, path, status, nbytes, ua in entries:
        ip_events[ip].append((ts, path, status, ua))
        if classify_ua(ua) == "bot":
            # Normalise UA: strip version noise for grouping
            key = ua[:80]
            bot_counts[key] += 1
            bot_statuses[key][status] += 1

    # ── Organic sessions: IP requested HTML + at least one static asset ───────
    organic_ips = set()
    for ip, evts in ip_events.items():
        evts.sort()
        # Slide a 30-second window
        for i, (ts, path, status, ua) in enumerate(evts):
            if STATIC.search(path):
                continue  # start window on an HTML request
            if status not in (200, 301, 302):
                continue
            if classify_ua(ua) == "bot":
                continue
            # Check if a static asset was fetched within the window
            window_end = ts + SESSION_WINDOW
            for ts2, path2, _, _ in evts[i+1:]:
                if ts2 > window_end:
                    break
                if STATIC.search(path2):
                    organic_ips.add(ip)
                    break

    # ── Anonymous bot-like traffic (unknown UA, no static assets) ─────────────
    anon_ips = defaultdict(int)
    for ip, evts in ip_events.items():
        if ip in organic_ips:
            continue
        for ts, path, status, ua in evts:
            if classify_ua(ua) == "unknown":
                anon_ips[ip] += 1

    return bot_counts, bot_statuses, organic_ips, anon_ips, ip_events


def main():
    logfile = sys.argv[1] if len(sys.argv) > 1 else \
              "/var/log/nginx/de.example.com.access.log"

    print(f"Reading {logfile} …")
    entries = parse(logfile)
    print(f"{len(entries)} entries parsed.\n")

    bot_counts, bot_statuses, organic_ips, anon_ips, ip_events = analyse(entries)

    # ── Report: bots ──────────────────────────────────────────────────────────
    print("=" * 70)
    print(f"{'BOTS':} ({len(bot_counts)} distinct UAs)")
    print("=" * 70)
    for ua, count in sorted(bot_counts.items(), key=lambda x: -x[1]):
        statuses = "  ".join(f"{s}×{n}" for s, n in sorted(bot_statuses[ua].items()))
        print(f"  {count:5d}  {ua[:60]}")
        print(f"         {statuses}")
    print()

    # ── Report: organic ───────────────────────────────────────────────────────
    print("=" * 70)
    print(f"ORGANIC SESSIONS ({len(organic_ips)} distinct IPs)")
    print("=" * 70)
    for ip in sorted(organic_ips):
        evts = ip_events[ip]
        pages = [p for _, p, s, _ in evts if not STATIC.search(p) and s == 200]
        print(f"  {ip:20s}  {len(evts):4d} req   pages: {', '.join(pages[:5])}")
    print()

    # ── Report: anonymous ─────────────────────────────────────────────────────
    print("=" * 70)
    print(f"ANONYMOUS / UNIDENTIFIED ({len(anon_ips)} IPs, unknown UA, no static pulls)")
    print("=" * 70)
    for ip, count in sorted(anon_ips.items(), key=lambda x: -x[1])[:20]:
        sample_ua = next((ua for _, _, _, ua in ip_events[ip]), "")
        print(f"  {ip:20s}  {count:4d} req   {sample_ua[:60]}")


if __name__ == "__main__":
    main()
