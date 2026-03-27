"""WSGI entry point."""
import logging
import os

# Configure logging before importing the app so all loggers inherit the level.
_verbose = os.environ.get("VERBOSE", "1") == "1"
logging.basicConfig(
    level=logging.INFO if _verbose else logging.WARNING,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Keep Werkzeug and noisy APScheduler internals quiet, but let job lifecycle through
logging.getLogger("apscheduler.executors").setLevel(logging.INFO)
logging.getLogger("apscheduler.scheduler").setLevel(logging.INFO)
logging.getLogger("apscheduler.threadpool").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
