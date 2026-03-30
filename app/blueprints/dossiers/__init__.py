from flask import Blueprint

bp = Blueprint("dossiers", __name__)

from . import views  # noqa: E402, F401
