"""SQLite database for histsearch."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "histsearch.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init():
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS topics (
            id          INTEGER PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            active      INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS search_runs (
            id           INTEGER PRIMARY KEY,
            topic_id     INTEGER NOT NULL REFERENCES topics(id),
            query        TEXT NOT NULL,
            engine       TEXT NOT NULL,
            ran_at       TEXT NOT NULL,
            result_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS urls (
            id             INTEGER PRIMARY KEY,
            topic_id       INTEGER NOT NULL REFERENCES topics(id),
            url            TEXT NOT NULL UNIQUE,
            domain         TEXT NOT NULL,
            discovered_at  TEXT NOT NULL,
            source_query   TEXT,
            status         TEXT NOT NULL DEFAULT 'new',
            fail_count     INTEGER NOT NULL DEFAULT 0,
            last_attempt   TEXT
        );

        CREATE TABLE IF NOT EXISTS articles (
            id                     INTEGER PRIMARY KEY,
            url_id                 INTEGER NOT NULL UNIQUE REFERENCES urls(id),
            url                    TEXT NOT NULL,
            title                  TEXT,
            extracted_text         TEXT,
            raw_html_path          TEXT,
            date_internet          TEXT,
            date_historical        TEXT,
            date_candidates        TEXT,
            date_selected          TEXT,
            prompt_injection_flag  INTEGER NOT NULL DEFAULT 0,
            prompt_injection_notes TEXT,
            review_status          TEXT NOT NULL DEFAULT 'pending',
            extracted_at           TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS domains (
            id          INTEGER PRIMARY KEY,
            domain      TEXT NOT NULL UNIQUE,
            js_required INTEGER NOT NULL DEFAULT 0,
            js_enabled  INTEGER NOT NULL DEFAULT 0,
            blocked     INTEGER NOT NULL DEFAULT 0,
            note        TEXT
        );
        """)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Topics ────────────────────────────────────────────────────────────────────

def get_active_topic(conn) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM topics WHERE active=1").fetchone()


def set_topic(name: str) -> sqlite3.Row:
    with connect() as conn:
        conn.execute("UPDATE topics SET active=0")
        conn.execute(
            "INSERT INTO topics(name, active, created_at) VALUES(?,1,?) "
            "ON CONFLICT(name) DO UPDATE SET active=1",
            (name, now_iso()),
        )
        return conn.execute("SELECT * FROM topics WHERE name=?", (name,)).fetchone()


# ── URLs ──────────────────────────────────────────────────────────────────────

def add_urls(topic_id: int, urls: list[tuple[str, str, str]]) -> int:
    """Insert (url, domain, source_query) tuples. Skip duplicates. Returns new count."""
    added = 0
    with connect() as conn:
        for url, domain, query in urls:
            try:
                conn.execute(
                    "INSERT INTO urls(topic_id,url,domain,discovered_at,source_query) "
                    "VALUES(?,?,?,?,?)",
                    (topic_id, url, domain, now_iso(), query),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass  # already known
    return added


def get_pending_urls(topic_id: int, limit: int = 50) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT u.*, d.js_enabled FROM urls u "
            "LEFT JOIN domains d ON d.domain=u.domain "
            "WHERE u.topic_id=? AND u.status IN ('new','js_required') "
            "  AND (u.status='new' OR d.js_enabled=1) "
            "ORDER BY u.id LIMIT ?",
            (topic_id, limit),
        ).fetchall()


def mark_url(url_id: int, status: str, fail: bool = False):
    with connect() as conn:
        if fail:
            conn.execute(
                "UPDATE urls SET status=?, fail_count=fail_count+1, last_attempt=? WHERE id=?",
                (status, now_iso(), url_id),
            )
        else:
            conn.execute(
                "UPDATE urls SET status=?, last_attempt=? WHERE id=?",
                (status, now_iso(), url_id),
            )


# ── Articles ──────────────────────────────────────────────────────────────────

def save_article(url_id: int, url: str, data: dict):
    with connect() as conn:
        conn.execute(
            """INSERT INTO articles(
                url_id, url, title, extracted_text, raw_html_path,
                date_internet, date_historical, date_candidates, date_selected,
                prompt_injection_flag, prompt_injection_notes,
                review_status, extracted_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,'pending',?)
            ON CONFLICT(url_id) DO UPDATE SET
                title=excluded.title,
                extracted_text=excluded.extracted_text,
                raw_html_path=excluded.raw_html_path,
                date_internet=excluded.date_internet,
                date_historical=excluded.date_historical,
                date_candidates=excluded.date_candidates,
                date_selected=excluded.date_selected,
                prompt_injection_flag=excluded.prompt_injection_flag,
                prompt_injection_notes=excluded.prompt_injection_notes,
                extracted_at=excluded.extracted_at""",
            (
                url_id, url,
                data.get("title"),
                data.get("text"),
                data.get("raw_html_path"),
                data.get("date_internet"),
                data.get("date_historical"),
                json.dumps(data.get("date_candidates", [])),
                data.get("date_selected"),
                1 if data.get("injection_flag") else 0,
                data.get("injection_notes"),
                now_iso(),
            ),
        )


def get_articles(status: str = "pending", limit: int = 50, offset: int = 0) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT a.*, u.domain FROM articles a JOIN urls u ON u.id=a.url_id "
            "WHERE a.review_status=? ORDER BY a.date_selected, a.id LIMIT ? OFFSET ?",
            (status, limit, offset),
        ).fetchall()


def get_article(article_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT a.*, u.domain, u.source_query FROM articles a JOIN urls u ON u.id=a.url_id "
            "WHERE a.id=?", (article_id,)
        ).fetchone()


def set_article_status(article_id: int, status: str):
    with connect() as conn:
        conn.execute("UPDATE articles SET review_status=? WHERE id=?", (status, article_id))


def set_article_date(article_id: int, date_str: str):
    with connect() as conn:
        conn.execute("UPDATE articles SET date_selected=? WHERE id=?", (date_str, article_id))


# ── Domains ───────────────────────────────────────────────────────────────────

def upsert_domain(domain: str, **kwargs):
    with connect() as conn:
        existing = conn.execute("SELECT id FROM domains WHERE domain=?", (domain,)).fetchone()
        if existing:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            conn.execute(f"UPDATE domains SET {sets} WHERE domain=?", (*kwargs.values(), domain))
        else:
            conn.execute(
                "INSERT INTO domains(domain) VALUES(?)", (domain,)
            )
            if kwargs:
                sets = ", ".join(f"{k}=?" for k in kwargs)
                conn.execute(f"UPDATE domains SET {sets} WHERE domain=?", (*kwargs.values(), domain))


def get_domains() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT d.*, "
            "  (SELECT COUNT(*) FROM urls u WHERE u.domain=d.domain) as url_count,"
            "  (SELECT COUNT(*) FROM urls u WHERE u.domain=d.domain AND u.status='js_required') as js_count "
            "FROM domains d ORDER BY js_count DESC, url_count DESC"
        ).fetchall()


# ── Stats ─────────────────────────────────────────────────────────────────────

def stats(topic_id: int) -> dict:
    with connect() as conn:
        url_stats = conn.execute(
            "SELECT status, COUNT(*) as n FROM urls WHERE topic_id=? GROUP BY status",
            (topic_id,)
        ).fetchall()
        art_stats = conn.execute(
            "SELECT review_status, COUNT(*) as n FROM articles a "
            "JOIN urls u ON u.id=a.url_id WHERE u.topic_id=? GROUP BY review_status",
            (topic_id,)
        ).fetchall()
        runs = conn.execute(
            "SELECT COUNT(*) as n FROM search_runs WHERE topic_id=?", (topic_id,)
        ).fetchone()
        return {
            "urls": {r["status"]: r["n"] for r in url_stats},
            "articles": {r["review_status"]: r["n"] for r in art_stats},
            "search_runs": runs["n"],
        }
