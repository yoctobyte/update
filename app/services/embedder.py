"""Generate and store embeddings for articles using a local sentence-transformers model."""
import logging
import threading
import struct

from ..extensions import db
from ..models import Article
from ..config import Config

logger = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()
_embed_lock = threading.Lock()  # prevent concurrent embedding jobs on Pi


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                import torch
                from sentence_transformers import SentenceTransformer
                torch.set_num_threads(2)
                logger.info("Loading embedding model %s...", Config.EMBEDDING_MODEL)
                _model = SentenceTransformer(Config.EMBEDDING_MODEL)
                logger.info("Embedding model loaded.")
    return _model


def _to_bytes(vector) -> bytes:
    """Convert a numpy float32 array to raw bytes for SQLite storage."""
    import numpy as np
    arr = np.array(vector, dtype=np.float32)
    return arr.tobytes()


def _to_vec_bytes(vector) -> bytes:
    """Pack as little-endian float32 for sqlite-vec."""
    import numpy as np
    arr = np.array(vector, dtype=np.float32)
    return struct.pack(f"{len(arr)}f", *arr)


def embed_pending(app, batch_size: int = 16) -> int:
    """Embed articles that have no embedding yet. Returns count processed."""
    if not _embed_lock.acquire(blocking=False):
        logger.debug("Embedding job already running, skipping.")
        return 0

    try:
        with app.app_context():
            articles = (
                Article.query
                .filter(Article.embedding.is_(None))
                .filter(Article.extracted_text.isnot(None))
                .limit(batch_size)
                .all()
            )
            if not articles:
                return 0

            model = _get_model()
            texts = [
                (a.short_text or a.extracted_text or a.title)[:512]
                for a in articles
            ]
            vectors = model.encode(texts, batch_size=batch_size, show_progress_bar=False)

            for article, vector in zip(articles, vectors):
                raw = _to_bytes(vector)
                article.embedding = raw

                # Also write to vec0 virtual table for KNN queries
                vec_bytes = _to_vec_bytes(vector)
                db.session.execute(
                    db.text(
                        "INSERT OR REPLACE INTO article_embeddings(article_id, embedding) "
                        "VALUES (:aid, :emb)"
                    ),
                    {"aid": article.id, "emb": vec_bytes},
                )

            db.session.commit()
            logger.info("Embedded %d articles.", len(articles))
            return len(articles)
    finally:
        _embed_lock.release()
