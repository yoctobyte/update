from datetime import datetime, timezone
from ..extensions import db


class Source(db.Model):
    __tablename__ = "sources"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    base_url = db.Column(db.String(500), nullable=False)
    type = db.Column(db.String(20), nullable=False, default="link_page")  # 'rss' | 'link_page' | 'article_page' | 'agenda'
    search_depth = db.Column(db.Integer, nullable=False, default=1)  # 0 = single page, 1 = follow links one level
    active = db.Column(db.Boolean, default=False, nullable=False)  # requires admin approval
    consecutive_failures = db.Column(db.Integer, default=0, nullable=False)
    last_successful_fetch = db.Column(db.DateTime, nullable=True)
    last_content_hash = db.Column(db.String(64), nullable=True)  # for article_page change detection
    # filter_scope: "none" = assume all content is local; "town" = only keep if primary town appears;
    # "region" = keep if primary town (geo_scope=local) or any region town (geo_scope=region)
    filter_scope = db.Column(db.String(10), nullable=False, default="none")
    # trusted_local: skip LLM geo classification and always set geo_scope="local"
    trusted_local = db.Column(db.Boolean, nullable=False, default=False)
    # JS rendering via Playwright — disabled by default, opt-in per source
    render_js = db.Column(db.Boolean, nullable=False, default=False)
    cookie_accept_selector = db.Column(db.String(300), nullable=True)  # CSS selector to click on consent walls
    last_fetch_new_count = db.Column(db.Integer, nullable=True)  # new items found in the most recent fetch
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    articles = db.relationship("Article", back_populates="source", lazy="dynamic")
    extraction_rules = db.relationship(
        "ExtractionRule", back_populates="source", lazy="dynamic",
        order_by="ExtractionRule.created_at.desc()"
    )

    def __repr__(self):
        return f"<Source {self.name}>"
