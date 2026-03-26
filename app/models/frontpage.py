from datetime import datetime, timezone
from ..extensions import db


class FrontpageItem(db.Model):
    __tablename__ = "frontpage_items"

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("articles.id"), nullable=False, index=True)
    added_at = db.Column(db.DateTime, nullable=False)
    removed_at = db.Column(db.DateTime, nullable=True, index=True)

    article = db.relationship("Article", backref=db.backref("frontpage_items", lazy="dynamic"))

    @property
    def is_active(self):
        return self.removed_at is None

    def __repr__(self):
        return f"<FrontpageItem article_id={self.article_id} active={self.is_active}>"
