import json
from pathlib import Path
from flask import Flask
from .config import Config
from .extensions import db, migrate, scheduler


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

    # Flask config
    app.config["SECRET_KEY"] = Config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = Config.database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["ADMIN_PASSWORD"] = Config.ADMIN_PASSWORD

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)

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
