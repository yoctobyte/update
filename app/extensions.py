import logging
import threading

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])
scheduler = BackgroundScheduler()

_ext_logger = logging.getLogger(__name__)


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_conn, _connection_record):
    """Load sqlite-vec and set pragmas on every new connection."""
    import sqlite_vec

    dbapi_conn.enable_load_extension(True)
    sqlite_vec.load(dbapi_conn)
    dbapi_conn.enable_load_extension(False)

    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA foreign_keys=ON")
    dbapi_conn.execute("PRAGMA busy_timeout=30000")  # wait up to 30 s before raising


@event.listens_for(Engine, "handle_error")
def _log_db_lock(exception_context):
    """When a database-is-locked error occurs, log which threads are alive."""
    orig = exception_context.original_exception
    if "database is locked" not in str(orig).lower():
        return
    alive = [f"{t.name}(daemon={t.daemon})" for t in threading.enumerate()]
    _ext_logger.error(
        "SQLite database locked — active threads: %s | statement: %s",
        ", ".join(alive),
        getattr(exception_context, "statement", "?"),
    )
