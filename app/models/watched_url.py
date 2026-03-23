from datetime import datetime, timezone
from ..extensions import db


class WatchedURL(db.Model):
    __tablename__ = "watched_urls"

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(1000), nullable=False, unique=True)
    label = db.Column(db.String(200), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    render_js = db.Column(db.Boolean, nullable=False, default=False)
    is_rss = db.Column(db.Boolean, nullable=True)  # None = not yet detected
    fetch_interval_hours = db.Column(db.Integer, nullable=False, default=6)
    last_fetched_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<WatchedURL {self.url[:60]}>"
