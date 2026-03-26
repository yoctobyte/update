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
                try:
                    # Prefer local cache — avoids HuggingFace HEAD requests on every startup
                    _model = SentenceTransformer(Config.EMBEDDING_MODEL, local_files_only=True)
                except RuntimeError as exc:
                    if "interpreter shutdown" in str(exc):
                        logger.warning("Embedding model load aborted — interpreter shutting down.")
                        return None
                    raise
                except Exception:
                    # Not cached yet — download once, then local_files_only works next time
                    logger.info("Model not in local cache, downloading...")
                    try:
                        _model = SentenceTransformer(Config.EMBEDDING_MODEL)
                    except RuntimeError as exc:
                        if "interpreter shutdown" in str(exc):
                            logger.warning("Embedding model load aborted — interpreter shutting down.")
                            return None
                        raise
                logger.info("Embedding model loaded.")
    return _model


def preload_model() -> None:
    """Load the embedding model in the background at startup so the first
    embed_pending job doesn't race with interpreter shutdown machinery.
    Skipped in the Werkzeug reloader parent process (which never serves requests)."""
    import os
    # WERKZEUG_RUN_MAIN is set only in the child process that actually serves.
    # The parent reloader process should not load the model — it exits on file changes.
    if os.environ.get("FLASK_DEBUG") == "1" and not os.environ.get("WERKZEUG_RUN_MAIN"):
        return

    def _load():
        try:
            _get_model()
        except Exception as exc:
            logger.warning("Background model preload failed: %s", exc)
    threading.Thread(target=_load, name="embedder-preload", daemon=True).start()


def _to_bytes(vector) -> bytes:
    """Convert a numpy float32 array to raw bytes for SQLite storage."""
    import numpy as np
    arr = np.array(vector, dtype=np.float32)
    return arr.tobytes()


def _to_vec_bytes(vector) -> bytes:
    """Pack as float32 for sqlite-vec."""
    import numpy as np
    arr = np.array(vector, dtype=np.float32)
    return struct.pack(f"{len(arr)}f", *arr)


def _to_vec_bytes_normalized(vector) -> bytes:
    """Pack as float32 for sqlite-vec, L2-normalized to unit length."""
    import numpy as np
    arr = np.array(vector, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return struct.pack(f"{len(arr)}f", *arr)


def embed_text(text: str):
    """Embed a single string. Returns a normalized numpy float32 array, or None."""
    import numpy as np
    model = _get_model()
    if model is None:
        return None
    vector = model.encode([text[:512]], show_progress_bar=False)[0]
    arr = np.array(vector, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr


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
            if model is None:
                logger.warning("Embedding model unavailable, skipping batch.")
                return 0
            texts = [
                (a.short_text or a.extracted_text or a.title)[:512]
                for a in articles
            ]
            vectors = model.encode(texts, batch_size=batch_size, show_progress_bar=False)

            for article, vector in zip(articles, vectors):
                raw = _to_bytes(vector)
                article.embedding = raw

                # Also write to vec0 virtual table for KNN queries
                # DELETE first — vec0 virtual tables don't support INSERT OR REPLACE
                vec_bytes = _to_vec_bytes(vector)
                vec_bytes_norm = _to_vec_bytes_normalized(vector)
                db.session.execute(
                    db.text("DELETE FROM article_embeddings WHERE article_id = :aid"),
                    {"aid": article.id},
                )
                db.session.execute(
                    db.text(
                        "INSERT INTO article_embeddings(article_id, embedding) "
                        "VALUES (:aid, :emb)"
                    ),
                    {"aid": article.id, "emb": vec_bytes},
                )
                db.session.execute(
                    db.text("DELETE FROM article_embeddings_norm WHERE article_id = :aid"),
                    {"aid": article.id},
                )
                db.session.execute(
                    db.text(
                        "INSERT INTO article_embeddings_norm(article_id, embedding) "
                        "VALUES (:aid, :emb)"
                    ),
                    {"aid": article.id, "emb": vec_bytes_norm},
                )

            db.session.commit()
            logger.info("Embedded %d articles.", len(articles))
            return len(articles)
    finally:
        _embed_lock.release()
