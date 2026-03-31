from ..extensions import db

LANE_TODAY = "today"
LANE_WEEK = "week"
LANE_CHOICES = {LANE_TODAY, LANE_WEEK}


class NewsLaneItem(db.Model):
    __tablename__ = "news_lane_items"

    id = db.Column(db.Integer, primary_key=True)
    lane = db.Column(db.String(10), nullable=False, index=True)  # 'today' | 'week'
    article_id = db.Column(db.Integer, db.ForeignKey("articles.id"), nullable=True, index=True)
    story_id = db.Column(db.Integer, db.ForeignKey("stories.id"), nullable=True, index=True)

    window_start = db.Column(db.DateTime, nullable=True)
    window_end = db.Column(db.DateTime, nullable=True)

    rank_score = db.Column(db.Float, nullable=True)
    freshness_score = db.Column(db.Float, nullable=True)
    blend_score = db.Column(db.Float, nullable=True)

    wins = db.Column(db.Integer, nullable=False, default=0)
    losses = db.Column(db.Integer, nullable=False, default=0)
    similars = db.Column(db.Integer, nullable=False, default=0)
    preference_wins = db.Column(db.Integer, nullable=False, default=0)
    preference_losses = db.Column(db.Integer, nullable=False, default=0)
    comparisons = db.Column(db.Integer, nullable=False, default=0)

    computed_at = db.Column(db.DateTime, nullable=True)
    removed_at = db.Column(db.DateTime, nullable=True, index=True)

    # Editorial overrides — survive scheduler recomputes
    pinned = db.Column(db.Boolean, nullable=False, default=False)
    suppressed = db.Column(db.Boolean, nullable=False, default=False)
    editorial_note = db.Column(db.Text, nullable=True)

    article = db.relationship("Article", backref=db.backref("lane_items", lazy="dynamic"))
    story = db.relationship("Story", backref=db.backref("lane_items", lazy="dynamic"))

    @property
    def is_active(self):
        return self.removed_at is None and not self.suppressed

    @property
    def display_title(self):
        if self.article_id and self.article:
            return self.article.title
        if self.story_id and self.story:
            return self.story.title
        return "?"

    def __repr__(self):
        ref = f"article={self.article_id}" if self.article_id else f"story={self.story_id}"
        return f"<NewsLaneItem lane={self.lane} {ref} blend={self.blend_score}>"
