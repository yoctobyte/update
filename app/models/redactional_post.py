from datetime import datetime, timezone
from ..extensions import db


class RedactionalPost(db.Model):
    __tablename__ = "redactional_posts"

    # Sentinel so templates can distinguish from Article without isinstance()
    is_redactional_post = True

    id           = db.Column(db.Integer, primary_key=True)
    topic        = db.Column(db.String(100), nullable=False, default="nieuws")
    title        = db.Column(db.String(500), nullable=False)
    content      = db.Column(db.Text, nullable=True)          # markdown
    image_path   = db.Column(db.String(500), nullable=True)   # filename in uploads dir
    image_alt    = db.Column(db.String(500), nullable=True)
    footer       = db.Column(db.String(200), nullable=False, default="van de redactie")
    published_at = db.Column(db.DateTime, nullable=False,
                             default=lambda: datetime.now(timezone.utc))
    created_at   = db.Column(db.DateTime, nullable=False,
                             default=lambda: datetime.now(timezone.utc))

    # Visibility
    visible  = db.Column(db.Boolean, nullable=False, default=True)   # inject into section feeds
    hide     = db.Column(db.Boolean, nullable=False, default=False)  # hide from /redactie pages

    # Pinning
    pinned          = db.Column(db.Boolean, nullable=False, default=False)
    pin_position    = db.Column(db.Integer, nullable=True, default=0)
    pin_expires_at  = db.Column(db.DateTime, nullable=True)   # None = never

    # Which section feeds to pin into (only active when pinned=True)
    pin_frontpage = db.Column(db.Boolean, nullable=False, default=False)
    pin_lokaal    = db.Column(db.Boolean, nullable=False, default=False)
    pin_alles     = db.Column(db.Boolean, nullable=False, default=False)
    pin_regio     = db.Column(db.Boolean, nullable=False, default=False)
    pin_provincie = db.Column(db.Boolean, nullable=False, default=False)
    pin_nationaal = db.Column(db.Boolean, nullable=False, default=False)
    pin_intl      = db.Column(db.Boolean, nullable=False, default=False)

    def is_pin_active(self) -> bool:
        """True if currently pinned and not yet expired."""
        if not self.pinned:
            return False
        if self.pin_expires_at is None:
            return True
        return datetime.utcnow() < self.pin_expires_at

    def __repr__(self):
        return f"<RedactionalPost {self.id} {self.title[:40]}>"
