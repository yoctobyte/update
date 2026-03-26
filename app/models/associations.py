from ..extensions import db

article_topics = db.Table(
    "article_topics",
    db.Column("article_id", db.Integer, db.ForeignKey("articles.id"), primary_key=True),
    db.Column("topic_id", db.Integer, db.ForeignKey("topics.id"), primary_key=True),
    db.Index("ix_article_topics_topic_id", "topic_id"),
)

article_stories = db.Table(
    "article_stories",
    db.Column("article_id", db.Integer, db.ForeignKey("articles.id"), primary_key=True),
    db.Column("story_id", db.Integer, db.ForeignKey("stories.id"), primary_key=True),
    db.Index("ix_article_stories_story_id", "story_id"),
)

story_topics = db.Table(
    "story_topics",
    db.Column("story_id", db.Integer, db.ForeignKey("stories.id"), primary_key=True),
    db.Column("topic_id", db.Integer, db.ForeignKey("topics.id"), primary_key=True),
    db.Index("ix_story_topics_topic_id", "topic_id"),
)

event_topics = db.Table(
    "event_topics",
    db.Column("event_id", db.Integer, db.ForeignKey("events.id"), primary_key=True),
    db.Column("topic_id", db.Integer, db.ForeignKey("topics.id"), primary_key=True),
    db.Index("ix_event_topics_topic_id", "topic_id"),
)

event_articles = db.Table(
    "event_articles",
    db.Column("event_id", db.Integer, db.ForeignKey("events.id"), primary_key=True),
    db.Column("article_id", db.Integer, db.ForeignKey("articles.id"), primary_key=True),
    db.Index("ix_event_articles_article_id", "article_id"),
)
