# Project Notes

## Meta / Handover

For shared multi-agent progress, handover, and git-state notes, read and update:

- `AGENTS.md`
- `docs/PROJECT_STATE.yaml`
- `docs/PROJECT_META.md`

Human-facing rule of thumb:

- `NOTES.md` = practical project instructions for a person opening the repo
- `AGENTS.md` = top-level agent compatibility entrypoint
- `docs/PROJECT_STATE.yaml` = structured project progress / goals / bugs / todos
- `docs/PROJECT_META.md` = deeper agent handover, status, and coordination notes

## First-time setup

After cloning, run these steps once before starting the app:

```bash
# 1. Generate .env with a secure secret key
./genenv.sh

# 2. Add your first town (sets admin password + initialises the database)
./addtown.sh <town> <port> <password>
# example: ./addtown.sh wageningen 6700 mypassword

# 3. Start all towns
./run.sh                  # production (gunicorn)
./run.sh --debug          # development (Werkzeug, single town, attached console)
./run.sh --test-render    # UI testing (read-only DB, no scheduler, port+100)
```

To rotate the secret key later (logs out all active sessions): run `./genenv.sh` again.

---

## Startup modes

### Production — `./run.sh`

Starts all towns in `towns.json` via gunicorn (1 worker, port from towns.json).
Runs `flask db upgrade` before starting each town. Scheduler starts and all
pipeline jobs fire immediately to drain any backlog since last run.

- PID file: `./<town>.pid`
- Scheduler: **enabled**
- Migrations: **run**
- Database: read-write

### Debug — `./run.sh --debug`

Runs a single town via Werkzeug's dev server (attached console, `use_reloader=False`).
Scheduler starts normally. Useful for backend development — not for UI testing, since
it runs on the production port and touches the live database.

- PID file: `./<town>.pid`
- Scheduler: **enabled**
- Migrations: **run**
- Database: read-write

> **Note:** `FLASK_DEBUG` is NOT exported in this mode. The Werkzeug reloader guard
> in `create_app()` is only meaningful when `use_reloader=True`. See
> `docs/postmortem_scheduler_startup_2026-03-27.md` for the full history.

### Test-render — `./run.sh --test-render`

Safe UI testing mode. Runs on port+100. Database is opened read-only at the OS
level (`sqlite?mode=ro`) so no writes are physically possible. Scheduler is
suppressed. Migrations are skipped. Admin write actions will surface SQLite
read-only errors (expected — this mode is for rendering only).

- PID file: `./<town>-test.pid`
- Scheduler: **disabled** (`TEST_RENDER=1` env var)
- Migrations: **skipped**
- Database: read-only (OS-level, `?mode=ro`)
- Port: configured port + 100

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `FLASK_SECRET_KEY` | yes | — | Session signing key. Set by `genenv.sh`. |
| `TOWN` | yes | — | Active town name. Set by run.sh / addtown.sh. |
| `PORT` | yes | — | Listen port. Set by run.sh from towns.json. |
| `ADMIN_PASSWORD_HASH` | yes | — | bcrypt hash. Set by run.sh from towns.json. |
| `DATA_ROOT` | no | `data/` | Root directory for per-town data. |
| `SITE_URL` | no | — | Public base URL, no trailing slash. Used in sitemap and absolute links. |
| `OPENAI_API_KEY` | no | `~/.config/openai_api_key.txt` | Falls back to key file if not set. |
| `OPENAI_MODEL_DEFAULT` | no | `gpt-4o-mini` | Model for routine LLM tasks (tagging, classification). |
| `OPENAI_MODEL_STRONG` | no | `gpt-4o` | Model for heavy tasks (summarisation, event import). |
| `EMBEDDING_MODEL` | no | `paraphrase-multilingual-MiniLM-L12-v2` | Sentence-transformers model for semantic search. |
| `FETCH_INTERVAL_MINUTES` | no | `15` | RSS/HTML fetch cadence. |
| `STORY_AUTOMERGE_THRESHOLD` | no | `0.92` | Cosine similarity above which articles auto-merge into a story. |
| `STORY_SUGGEST_THRESHOLD` | no | `0.85` | Cosine similarity above which a merge is suggested but not automatic. |
| `VERBOSE` | no | `1` | Set to `0` to suppress INFO logs. |
| `TEST_RENDER` | no | — | Set to `1` by `--test-render` mode. Disables scheduler, opens DB read-only. |
| `TESTING` | no | — | Set to `1` for test suites. Also disables scheduler. |

---

## Towns system

Each town is an independent deployment: its own database, config, cache, uploads,
port, and admin password. All towns are declared in `towns.json`:

```json
[
  { "town": "wageningen", "port": 6700, "password_hash": "<bcrypt>" }
]
```

`./addtown.sh <town> <port> <password>` hashes the password, appends the entry,
and runs `flask init-town` to create the data directory and initial config.

Data lives at `data/<town>/`:
```
data/<town>/
  database.db          # SQLite database (+ -shm, -wal when running)
  config.json          # Town identity: site_name, site_town, province, region_towns, …
  cache/html/          # Raw HTML fetch cache
  cache/snapshots/     # Timestamped gzip archive of all source fetches (from 2026-03-23)
  uploads/             # Admin-uploaded images (redactional posts, events)
```

---

## Data pipeline

Articles move through this pipeline on every scheduler cycle:

```
RSS/HTML sources
      │
      ▼ fetch_all_sources (every 15 min)
      │  fetch_all_watched (every 30 min for watched URLs)
      │
      ▼ extract_all_pending (every 5 min)
      │  LLM: title, summary, geo_scope, published_at extracted from raw HTML
      │  tag_untagged_articles (every 30 min)
      │  LLM: topic tags assigned
      │
      ▼ embed_pending (every 5 min)
      │  Sentence-transformer: 384-dim embedding stored in article_embeddings
      │
      ▼ cluster_new_articles (every 30 min)
      │  KNN over 30-day window → merge similar articles into Stories
      │
      ▼ evaluate_pending / update_frontpage (every 30 min)
         LLM: score article for frontpage relevance → frontpage_items
```

All jobs fire immediately at startup (`next_run_time=now`) to drain backlog.
A `misfire_grace_time=60s` prevents APScheduler from skipping them on slow starts.

---

## Scheduler guards

The scheduler must not start in:

| Context | Guard | Why |
|---|---|---|
| `flask db upgrade` / any Flask CLI | `sys.argv[0].stem == "flask"` | CLI fully imports `create_app()`; scheduler would fire all jobs during migration |
| Werkzeug reloader parent process | `FLASK_DEBUG=1` + not `WERKZEUG_RUN_MAIN` + not Flask CLI | Parent process only watches files; child (`WERKZEUG_RUN_MAIN=true`) is the real server |
| Test suite | `TESTING=1` env var or `app.config["TESTING"]` | Jobs would race with test assertions |
| Test-render mode | `TEST_RENDER=1` env var | Read-only DB + UI-only testing; pipeline jobs must not run |

See `docs/postmortem_scheduler_startup_2026-03-27.md` for a detailed incident
where the CLI and reloader-parent guards were missing.

---

## Article density modes

The util bar has three density toggles that control how article cards are rendered
in all list views (frontpage, lokaal, regio, provincie, etc.). Excluded: redactional
posts (always full), stories, agenda, ingezonden.

| Mode | Icon | What shows | Default |
|---|---|---|---|
| `compact` | ▤ | Title only | — |
| `condensed` | ▦ | Title + first sentence (to first `.`/`!`/`?`, max 300 chars / 50 words) | Mobile |
| `full` | ▩ | Complete card (summary, footer, favicons, date) | Desktop |

In `compact` or `condensed` mode, tapping a card expands it to full. Tapping
again navigates to the article detail page. The ↗ external link is always
clickable. Preference is saved in `localStorage` and applied before first paint
(no FOUC). Density buttons share the util bar with theme and font-size controls.

Implementation: `site.js` (init + button wiring), `density.js` (first-sentence
extraction + click handler), `main.css` section 13.

---

## Snapshot archive

From 2026-03-23 onward, all primary sources are archived as timestamped gzip
snapshots:

```
data/<town>/cache/snapshots/<url-hash>/<YYYYMMDD_HHMMSS>.gz
```

The `watched_urls` table drives this — RSS feeds snapshot hourly, HTML pages
every 6 hours.

**Whenever doing a major refactor or pipeline reset:** don't wait on live fetches.
Reprocess the archive instead. It can be used to:
- Backfill articles after a data model change
- Test new extraction rules offline
- Re-classify content after geo-scope or pipeline changes
- Seed a fresh database without depending on real-time availability of sources

---

## Git / branch workflow

```
main        stable; matches what is live. Never commit experimental work here.
dev         integration branch; features merge here first before promoting to main.
feature/*   short-lived; branch from dev, merge back to dev when done.
```

**While on `dev` or a feature branch:** do not restart or modify the running
production process. The live app runs from `main`. DB read queries are fine;
writes to the running instance are not.

Promote to main when dev is stable and tested:

```bash
git checkout main
git merge --no-ff dev
./run.sh   # restart production
```
