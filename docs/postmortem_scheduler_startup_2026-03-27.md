# Postmortem: Scheduler ran during migrations, then dead in server

**Date:** 2026-03-27
**Status:** Fixed

---

## What broke

Running `./run.sh --debug` produced this wrong sequence:

1. `flask db upgrade` → **all 10 scheduler jobs fired** (67 seconds of fetching, clustering, LLM calls)
2. Scheduler shut down via atexit
3. `python wsgi.py` started → **scheduler never started** → server appeared to hang (no jobs, no output)

---

## Root cause 1 — Scheduler ran during migrations

`run.sh` runs migrations with:
```bash
flask db upgrade
```

This imports the Flask app via `create_app()`. The guard that prevents the scheduler from starting looked like this:

```python
_is_reloader_parent = (
    os.environ.get("FLASK_DEBUG") == "1"
    and not os.environ.get("WERKZEUG_RUN_MAIN")
)
if not TESTING and not _is_reloader_parent:
    start_scheduler()
```

During `flask db upgrade`:
- `FLASK_DEBUG` is not set → `_is_reloader_parent = False`
- Scheduler starts, all 10 jobs fire immediately (`next_run_time=now`)
- When the migration process exits, atexit shuts the scheduler down

The guard only knew about two cases (testing, Werkzeug reloader). It had no awareness of the Flask CLI.

---

## Root cause 2 — Scheduler dead in the actual server

`run.sh --debug` started the server with:
```bash
FLASK_DEBUG=1 python wsgi.py
```

In `create_app()`:
- `FLASK_DEBUG=1` → checked
- `WERKZEUG_RUN_MAIN` → not set (never is, because `wsgi.py` uses `app.run(debug=False, use_reloader=False)`)
- Result: `_is_reloader_parent = True` → **scheduler blocked**

The `FLASK_DEBUG=1` env var was added when we were tinkering with debug mode. It has no actual effect on Flask behaviour here — `wsgi.py` hardcodes `debug=False, use_reloader=False` — but it was enough to trip the reloader-parent guard.

The guard was written for a real Werkzeug reloader scenario: parent process (file watcher) should not run the scheduler, child process (actual server, `WERKZEUG_RUN_MAIN=true`) should. When `use_reloader=False`, that child process never exists and `WERKZEUG_RUN_MAIN` is never set. The guard could not tell the difference.

---

## Observable symptoms

From the startup log:
- All 10 scheduler jobs ran and completed before Werkzeug printed a single line
- `RuntimeError: cannot schedule new futures after shutdown` appearing mid-run (ThreadPoolExecutor torn down by atexit while a long job was still finishing)
- After Werkzeug started: `* Debug mode: off` followed by silence — server was alive but scheduler was dead

---

## Fix

**`app/__init__.py`** — detect Flask CLI invocation explicitly:

```python
_is_flask_cli = bool(sys.argv) and Path(sys.argv[0]).stem == "flask"
_is_reloader_parent = (
    os.environ.get("FLASK_DEBUG") == "1"
    and not os.environ.get("WERKZEUG_RUN_MAIN")
    and not _is_flask_cli
)
if not TESTING and not _is_flask_cli and not _is_reloader_parent:
    start_scheduler()
```

`sys.argv[0]` is the `flask` script during any CLI command (`db upgrade`, `shell`, etc.) and `wsgi.py` when running the server. Reliable distinction.

**`run.sh`** — removed `FLASK_DEBUG=1` from the debug start command. It did nothing useful (overridden by `app.run(debug=False)`) and was the trigger for the broken reloader-parent guard.

---

## Lessons

- The Werkzeug reloader guard (`FLASK_DEBUG + not WERKZEUG_RUN_MAIN`) is only meaningful when `use_reloader=True`. With `use_reloader=False` it is a footgun: any process that has `FLASK_DEBUG=1` in the environment (for whatever reason) will silently lose its scheduler.
- `flask db upgrade` is not a no-op import — it fully initialises the app, starts extensions, and triggers `create_app()` side effects. Guard all "server-only" startup work against the Flask CLI.
- Stray env vars from debugging sessions (`FLASK_DEBUG=1`) can have non-obvious effects on app logic long after the debug session ends.
