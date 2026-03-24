import json
import os
import threading
import time
from pathlib import Path
from flask import Flask, request
import jinja2
from .config import Config
from .extensions import db, migrate, csrf, limiter, scheduler


class _ThrottledReloadLoader(jinja2.BaseLoader):
    """Wraps another Jinja2 loader and throttles mtime checks to once per
    `interval` seconds per template file. Within the interval, the cached
    compiled template is served directly — no stat() call. After the interval
    expires, a single stat() determines whether the file changed; only that
    template is reloaded if it did."""

    def __init__(self, wrapped: jinja2.BaseLoader, interval: int = 30):
        self._wrapped = wrapped
        self._interval = interval
        self._lock = threading.Lock()
        self._state: dict = {}  # filename -> {"mtime": float, "checked": float}

    def get_source(self, environment, template):
        source, filename, _ = self._wrapped.get_source(environment, template)
        loader = self

        def uptodate():
            if not filename:
                return True
            now = time.monotonic()
            with loader._lock:
                entry = loader._state.get(filename)
                if entry and now - entry["checked"] < loader._interval:
                    return True  # within window — skip stat
                try:
                    mtime = os.path.getmtime(filename)
                except OSError:
                    return False
                if entry is None:
                    loader._state[filename] = {"mtime": mtime, "checked": now}
                    return True
                changed = mtime != entry["mtime"]
                loader._state[filename] = {"mtime": mtime, "checked": now}
                return not changed

        return source, filename, uptodate

    def list_templates(self):
        return self._wrapped.list_templates()

_BAD_SECRETS = {"dev-secret-change-me", "change-me", "secret", "admin", "password", ""}


def create_app(town: str = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)

    # Resolve active town
    active_town = town or Config.TOWN
    if not active_town:
        raise RuntimeError("No town specified. Set TOWN env var or pass town= to create_app().")
    Config.TOWN = active_town

    # Ensure data directories exist
    db_dir = Path(Config.DATA_ROOT) / active_town
    db_dir.mkdir(parents=True, exist_ok=True)
    Config.town_cache_path().mkdir(parents=True, exist_ok=True)

    # Validate and load secrets
    secret_key = Config._require_env("FLASK_SECRET_KEY", known_bad=_BAD_SECRETS)

    # Flask config
    app.config["SECRET_KEY"] = secret_key
    app.config["SQLALCHEMY_DATABASE_URI"] = Config.database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # Password hash is optional at startup (not needed for migrations/CLI);
    # the login route will refuse if it is absent.
    app.config["ADMIN_PASSWORD_HASH"] = os.environ.get("ADMIN_PASSWORD_HASH", "")

    # Session cookie security
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False  # set True if serving over HTTPS

    # CSRF
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600  # 1 hour

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    # Security headers
    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    # Scheduler — MemoryJobStore since jobs are always re-registered at startup
    scheduler.configure(
        jobstores={"default": {"type": "memory"}},
        executors={"default": {"type": "threadpool", "max_workers": 2}},
        job_defaults={"coalesce": True, "max_instances": 1},
    )

    # Blueprints
    from .blueprints.main import bp as main_bp
    from .blueprints.admin import bp as admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # Template globals — site identity from town config.json
    _town_cfg: dict = {}
    _cfg_path = Config.town_config_path()
    if _cfg_path.exists():
        try:
            _town_cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    app.jinja_env.globals.update(
        site_name=_town_cfg.get("site_name", "Lokaal Nieuws"),
        site_town=_town_cfg.get("site_town", active_town.title()),
    )

    # Throttled template auto-reload: stat each file at most once per 30s;
    # only recompile the template that actually changed.
    app.jinja_env.auto_reload = True
    app.jinja_env.loader = _ThrottledReloadLoader(app.jinja_env.loader, interval=30)

    # CLI commands
    from .cli.commands import register_commands
    register_commands(app)

    # Start scheduler (not in testing)
    if not app.config.get("TESTING"):
        from .services.scheduler_jobs import register_jobs
        register_jobs(scheduler, app)
        if not scheduler.running:
            scheduler.start()

    return app
