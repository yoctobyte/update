# Project Notes

## First-time setup

After cloning, run these steps once before starting the app:

```bash
# 1. Generate .env with a secure secret key
./genenv.sh

# 2. Add your first town (sets admin password + initialises the database)
./addtown.sh <town> <port> <password>
# example: ./addtown.sh wageningen 6700 mypassword

# 3. Start all towns
./run.sh           # production (gunicorn)
./run.sh --debug   # development (Werkzeug reloader)
```

To rotate the secret key later (logs out all active sessions): run `./genenv.sh` again.

## Snapshot archive

From 2026-03-23 onward, all primary sources are archived as timestamped gzip snapshots:

```
data/wageningen/cache/snapshots/<url-hash>/<YYYYMMDD_HHMMSS>.gz
```

The watched_urls table drives this — RSS feeds snapshot hourly, HTML pages every 6 hours.

**Whenever doing a major refactor or pipeline reset:** don't wait on live fetches.
Reprocess the archive instead. It can be used to:
- Backfill articles after a data model change
- Test new extraction rules offline
- Re-classify content after geo-scope or pipeline changes
- Seed a fresh database without depending on real-time availability of sources
