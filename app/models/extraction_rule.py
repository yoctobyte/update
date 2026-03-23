from datetime import datetime, timezone
from ..extensions import db


class ExtractionRule(db.Model):
    __tablename__ = "extraction_rules"

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("sources.id"), nullable=False, index=True)
    rule_type = db.Column(db.String(20), nullable=False)  # 'regex' | 'css_selector'
    rule_definition = db.Column(db.Text, nullable=False)
    rule_purpose = db.Column(db.String(10), nullable=False, default="content")  # 'links' | 'content' | 'events'
    approved = db.Column(db.Boolean, default=False, nullable=False)
    scope = db.Column(db.String(10), nullable=False, default="persistent")  # 'once' | 'persistent'
    valid_from = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    valid_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    source = db.relationship("Source", back_populates="extraction_rules")

    @property
    def url_pattern(self) -> str:
        """
        Human-readable scope of this rule.
        '>' is not a valid URL character — we use it to mean 'pages linked from this source'.
        '[events]' denotes event extraction from the page itself.
          www.stadwageningen.nl           → rule applies to the listing page itself (links)
          www.stadwageningen.nl >         → rule applies to pages linked from that source (content)
          www.stadwageningen.nl [events]  → rule extracts event objects from the page (events)
        """
        base = self.source.base_url.rstrip("/")
        if self.rule_purpose == "links":
            return base
        elif self.rule_purpose == "events":
            return f"{base} [events]"
        else:
            return f"{base} >"

    @property
    def is_active(self):
        if not self.approved:
            return False
        if self.valid_until and datetime.now(timezone.utc) > self.valid_until:
            return False
        return True

    def __repr__(self):
        return f"<ExtractionRule {self.rule_type} source={self.source_id}>"
