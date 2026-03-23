"""Opinion piece submitted by any visitor (or admin under a pen name)."""
import uuid
from datetime import datetime, timezone
from ..extensions import db


def _new_token() -> str:
    return uuid.uuid4().hex


class Opinion(db.Model):
    __tablename__ = "opinions"

    id          = db.Column(db.Integer, primary_key=True)
    # Secret token — bearer can edit until published
    token       = db.Column(db.String(32), unique=True, nullable=False, default=_new_token)
    pen_name    = db.Column(db.String(100), nullable=False)
    title       = db.Column(db.String(300), nullable=False)
    body        = db.Column(db.Text, nullable=False)
    # Private — never shown publicly; used only to notify submitter if desired
    email       = db.Column(db.String(200), nullable=True)
    # pending | published | rejected
    status      = db.Column(db.String(20), nullable=False, default="pending")
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at  = db.Column(db.DateTime(timezone=True),
                            default=lambda: datetime.now(timezone.utc))
    updated_at  = db.Column(db.DateTime(timezone=True),
                            default=lambda: datetime.now(timezone.utc),
                            onupdate=lambda: datetime.now(timezone.utc))

    @property
    def editable(self) -> bool:
        """Can still be edited by the submitter (not yet published/rejected)."""
        return self.status == "pending"
