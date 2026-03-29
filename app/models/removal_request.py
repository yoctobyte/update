"""Removal / takedown requests submitted via the public form."""
from datetime import datetime, timezone
from ..extensions import db


class RemovalRequest(db.Model):
    __tablename__ = "removal_requests"

    id           = db.Column(db.Integer, primary_key=True)
    # 'tip' | 'url' | 'source'
    request_type = db.Column(db.String(20), nullable=False)

    # What is being reported
    target       = db.Column(db.Text)        # URL, article URL, or RSS/site URL
    description  = db.Column(db.Text, nullable=False)

    # Contact (optional for tip, required for url/source)
    contact_name = db.Column(db.String(200))
    email        = db.Column(db.String(200))
    phone        = db.Column(db.String(100))
    phone_app    = db.Column(db.String(50))  # e.g. "WhatsApp", "Telegram"

    # Admin workflow
    status       = db.Column(db.String(20), default="pending", nullable=False)
    admin_notes  = db.Column(db.Text)

    created_at   = db.Column(db.DateTime(timezone=True),
                             default=lambda: datetime.now(timezone.utc))
    updated_at   = db.Column(db.DateTime(timezone=True),
                             default=lambda: datetime.now(timezone.utc),
                             onupdate=lambda: datetime.now(timezone.utc))
