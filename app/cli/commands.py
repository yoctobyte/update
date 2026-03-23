import json
import click
from pathlib import Path
from flask import Flask


def register_commands(app: Flask) -> None:

    @app.cli.command("init-town")
    @click.argument("town")
    def init_town(town: str):
        """Initialize data directory and database for a town."""
        from flask_migrate import upgrade
        from ..config import Config
        from ..extensions import db
        from ..models import ExtractionRule, Source

        Config.TOWN = town
        data_dir = Path(Config.DATA_ROOT) / town
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "cache" / "html").mkdir(parents=True, exist_ok=True)

        # Copy seed config if not yet present
        config_path = data_dir / "config.json"
        seeds_path = Path("seeds") / "dutch_news_sources.json"
        if not config_path.exists() and seeds_path.exists():
            config_path.write_text(seeds_path.read_text(encoding="utf-8"), encoding="utf-8")
            click.echo(f"Seed config copied to {config_path}")

        # Run migrations
        with app.app_context():
            upgrade()
            click.echo("Database migrated.")

            # Load seeded sources and rules
            if config_path.exists():
                _seed_sources(config_path)
                click.echo("Seed sources loaded.")

        click.echo(f"Town '{town}' initialized.")

    @app.cli.command("seed-rules")
    def seed_rules():
        """Re-apply seed extraction rules without wiping existing ones."""
        from ..config import Config
        config_path = Config.town_config_path()
        if not config_path.exists():
            click.echo("No config.json found. Run init-town first.")
            return
        with app.app_context():
            _seed_sources(config_path)
            click.echo("Seed rules applied.")

    @app.cli.command("fetch-now")
    def fetch_now():
        """Trigger an immediate fetch of all active sources."""
        from ..services.fetcher import fetch_all_active
        with app.app_context():
            fetch_all_active(app)
            click.echo("Fetch complete.")

    @app.cli.command("embed-now")
    def embed_now():
        """Trigger an immediate embedding run."""
        from ..services.embedder import embed_pending
        total = 0
        with app.app_context():
            while True:
                n = embed_pending(app)
                total += n
                if n == 0:
                    break
        click.echo(f"Embedded {total} articles.")

    @app.cli.command("cluster-now")
    def cluster_now():
        """Trigger an immediate story clustering run."""
        from ..services.clustering import cluster_new_articles
        with app.app_context():
            cluster_new_articles(app)
            click.echo("Clustering complete.")

    @app.cli.command("backfill-geo")
    def backfill_geo():
        """Classify geo_scope for articles that were extracted before geo classification was added."""
        from ..extensions import db
        from ..models import Article
        from ..services.extractor import _apply_geo
        with app.app_context():
            articles = (
                Article.query
                .filter(Article.geo_scope.is_(None))
                .filter(db.or_(Article.extracted_text.isnot(None), Article.summary.isnot(None)))
                .all()
            )
            updated = 0
            for article in articles:
                _apply_geo(article, article.source)
                if article.geo_scope is not None:
                    updated += 1
            db.session.commit()
            click.echo(f"Classified {updated} of {len(articles)} articles.")

    @app.cli.command("reset-articles")
    def reset_articles():
        """Delete all articles, stories, and merge logs so they are re-fetched and re-summarized."""
        from ..extensions import db
        with app.app_context():
            db.session.execute(db.text("DELETE FROM article_topics"))
            db.session.execute(db.text("DELETE FROM article_stories"))
            db.session.execute(db.text("DELETE FROM event_articles"))
            db.session.execute(db.text("DELETE FROM story_merge_logs"))
            db.session.execute(db.text("DELETE FROM stories"))
            db.session.execute(db.text("DELETE FROM articles"))
            try:
                db.session.execute(db.text("DELETE FROM article_embeddings"))
            except Exception:
                pass  # virtual table may not exist on older installs
            db.session.commit()
            click.echo("Done. Run fetch-now to re-ingest.")


def _seed_sources(config_path: Path) -> None:
    from ..extensions import db
    from ..models import Source, ExtractionRule
    from datetime import datetime, timezone

    data = json.loads(config_path.read_text(encoding="utf-8"))
    for item in data.get("sources", []):
        existing = Source.query.filter_by(base_url=item["base_url"]).first()
        if not existing:
            source = Source(
                name=item["name"],
                base_url=item["base_url"],
                type=item.get("type", "link_page"),
                active=item.get("active", False),
            )
            db.session.add(source)
            db.session.flush()
        else:
            source = existing

        for rule_data in item.get("extraction_rules", []):
            # Don't duplicate pre-approved rules
            exists = ExtractionRule.query.filter_by(
                source_id=source.id,
                rule_definition=rule_data["rule_definition"],
            ).first()
            if not exists:
                rule = ExtractionRule(
                    source_id=source.id,
                    rule_type=rule_data["rule_type"],
                    rule_definition=rule_data["rule_definition"],
                    rule_purpose=rule_data.get("rule_purpose", "content"),
                    approved=rule_data.get("approved", False),
                    scope=rule_data.get("scope", "persistent"),
                    valid_from=datetime.now(timezone.utc),
                )
                db.session.add(rule)

    db.session.commit()
