"""Dossiers — curated long-form background articles rendered from Markdown."""
import logging
from pathlib import Path

import markdown as _md
from flask import abort, render_template
from markupsafe import Markup

from . import bp
from ...config import Config, PROJECT_ROOT

logger = logging.getLogger(__name__)

# Root of the dossiers directory (repo root / dossiers)
_DOSSIERS_ROOT = PROJECT_ROOT / "dossiers"
_YAML_PATH = _DOSSIERS_ROOT / "published.yaml"


def _load_yaml() -> list[dict]:
    """Load and parse published.yaml. Returns list of dossier dicts."""
    import yaml
    if not _YAML_PATH.exists():
        return []
    with _YAML_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("dossiers", [])


def _published() -> list[dict]:
    """Return only published dossiers, sorted by published_date descending."""
    entries = [d for d in _load_yaml() if d.get("publish")]
    entries.sort(key=lambda d: d.get("published_date", ""), reverse=True)
    return entries


def _cache_path(dossier_id: str) -> Path:
    return Config.DATA_ROOT / Config.TOWN / "dossiers_cache" / f"{dossier_id}.html"


def _render_to_cache(entry: dict) -> str:
    """Render a dossier's Markdown to HTML, write to cache, return HTML string."""
    md_path = _DOSSIERS_ROOT / entry["path"]
    if not md_path.exists():
        logger.warning("Dossier markdown not found: %s", md_path)
        return ""
    text = md_path.read_text(encoding="utf-8")
    html = _md.markdown(text, extensions=["nl2br", "fenced_code", "tables", "toc"])
    cache = _cache_path(entry["id"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(html, encoding="utf-8")
    return html


def _get_html(entry: dict) -> str:
    """Return cached HTML for a dossier, rendering if cache is missing."""
    cache = _cache_path(entry["id"])
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    return _render_to_cache(entry)


def refresh_all_dossiers() -> int:
    """Re-render all published dossiers to cache. Returns count refreshed."""
    count = 0
    for entry in _published():
        _render_to_cache(entry)
        count += 1
    return count


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/dossiers")
def index():
    return render_template("dossiers/index.html", dossiers=_published())


@bp.route("/dossiers/<dossier_id>")
def detail(dossier_id: str):
    entry = next(
        (d for d in _load_yaml() if d["id"] == dossier_id and d.get("publish")),
        None,
    )
    if entry is None:
        abort(404)
    html = Markup(_get_html(entry))
    return render_template("dossiers/detail.html", dossier=entry, content=html)
