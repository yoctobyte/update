from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/admin")

from . import views  # noqa: E402, F401
