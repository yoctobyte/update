import json
import os
from pathlib import Path
from flask import Flask, request
from .config import Config
from .extensions import db, migrate, csrf, limiter, scheduler

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
    Config.uploads_path().mkdir(parents=True, exist_ok=True)

    # Validate and load secrets
    secret_key = Config._require_env("FLASK_SECRET_KEY", known_bad=_BAD_SECRETS)

    # Flask config
    app.config["SECRET_KEY"] = secret_key
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["SQLALCHEMY_DATABASE_URI"] = Config.database_uri()
    # Password hash is optional at startup (not needed for migrations/CLI);
    # the login route will refuse if it is absent.
    app.config["ADMIN_PASSWORD_HASH"] = os.environ.get("ADMIN_PASSWORD_HASH", "")

    # Session cookie security
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"

    # Upload size limit — prevents DoS via large file uploads
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB

    # CSRF
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600  # 1 hour

    # Disable static file caching in test-render mode
    if os.environ.get("TEST_RENDER"):
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)

    if os.environ.get("TEST_RENDER"):
        # Prevent all writes via PRAGMA — uses normal SQLAlchemy connection
        # (WAL-compatible, no dialect bypass issues).
        from sqlalchemy import event as _sa_event
        with app.app_context():
            @_sa_event.listens_for(db.engine, "connect")
            def _set_query_only(dbapi_conn, _):
                dbapi_conn.execute("PRAGMA query_only = ON")
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
    csrf.exempt(main_bp)

    # Markdown filter
    import markdown as _md
    from markupsafe import Markup as _Markup
    app.jinja_env.filters["markdown"] = lambda text: _Markup(
        _md.markdown(text or "", extensions=["nl2br", "fenced_code"])
    )

    # Template globals — site identity from town config.json
    _town_cfg: dict = {}
    _cfg_path = Config.town_config_path()
    if _cfg_path.exists():
        try:
            _town_cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    site_town = _town_cfg.get("site_town", active_town.title())
    from .blueprints.main.views import slugify as _slugify
    from flask import url_for as _url_for

    def _article_url(article):
        return _url_for("main.article_detail", article_id=article.id, slug=_slugify(article.title or ""))

    def _redactie_url(post):
        return _url_for("main.redactie_post", post_id=post.id, slug=_slugify(post.title or ""))

    def _event_url(event):
        if getattr(event, "is_redactie", False):
            return _url_for("main.redactie_event_detail", event_id=event.id, slug=_slugify(event.title or ""))
        return _url_for("main.event_detail", event_id=event.id, slug=_slugify(event.title or ""))

    app.jinja_env.globals.update(
        site_name=_town_cfg.get("site_name", "Lokaal Nieuws"),
        site_town=site_town,
        article_url=_article_url,
        redactie_url=_redactie_url,
        event_url=_event_url,
    )

    # Register /<town_slug> as the canonical local news URL.
    # /lokaal redirects here (301). The view function is defined in the blueprint
    # but not attached to a route there, so we can give it the right URL here.
    from .blueprints.main.views import lokaal as _lokaal_view
    town_slug = site_town.lower()
    app.add_url_rule(f"/{town_slug}", endpoint="main.lokaal", view_func=_lokaal_view)

    # CLI commands
    from .cli.commands import register_commands
    register_commands(app)

    # Start scheduler only when actually serving requests.
    # Skip in:
    #   - Flask CLI commands (flask db upgrade, flask shell, etc.) — detected via
    #     sys.argv[0] name being "flask"; the scheduler would run jobs during
    #     migrations and exit on atexit, wasting resources.
    #   - Werkzeug reloader *parent* process (forks a child to serve; only the
    #     child sets WERKZEUG_RUN_MAIN=true and should run the scheduler).
    #   - Test runs.
    import sys as _sys
    from pathlib import Path as _Path
    _is_flask_cli = bool(_sys.argv) and _Path(_sys.argv[0]).stem == "flask"
    _is_reloader_parent = (
        os.environ.get("FLASK_DEBUG") == "1"
        and not os.environ.get("WERKZEUG_RUN_MAIN")
        and not _is_flask_cli  # CLI already excluded above
    )
    if (not app.config.get("TESTING") and not os.environ.get("TESTING")
            and not os.environ.get("TEST_RENDER")
            and not _is_flask_cli and not _is_reloader_parent):
        import atexit
        from .services.scheduler_jobs import register_jobs
        register_jobs(scheduler, app)
        if not scheduler.running:
            scheduler.start()

            def _shutdown_scheduler():
                try:
                    scheduler.pause()   # stop dispatching jobs immediately
                except Exception:
                    pass
                try:
                    scheduler.shutdown(wait=False)
                except Exception:
                    pass

            atexit.register(_shutdown_scheduler)

    return app
