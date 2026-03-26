"""Add article_embeddings_norm virtual table with L2-normalized vectors.

The existing article_embeddings table stores raw (non-unit) vectors, making
L2 distances exceed the [0,2] range and breaking the cosine-similarity formula.
This table stores the same vectors normalized to unit length, giving clean
cosine-compatible distances in [0,2] → similarities in [0,1].

Revision ID: 0018
Revises: 0017
"""
import math
import struct

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS article_embeddings_norm "
        "USING vec0(article_id INTEGER PRIMARY KEY, embedding FLOAT[384])"
    )

    # Backfill from articles.embedding (raw float32 bytes)
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, embedding FROM articles WHERE embedding IS NOT NULL")
    ).fetchall()

    for row in rows:
        raw = bytes(row.embedding)
        if len(raw) != 384 * 4:
            continue
        floats = struct.unpack(f"384f", raw)
        norm = math.sqrt(sum(f * f for f in floats))
        if norm == 0:
            continue
        normalized = tuple(f / norm for f in floats)
        vec_bytes = struct.pack(f"384f", *normalized)
        conn.execute(
            sa.text("DELETE FROM article_embeddings_norm WHERE article_id = :aid"),
            {"aid": row.id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO article_embeddings_norm(article_id, embedding) "
                "VALUES (:aid, :emb)"
            ),
            {"aid": row.id, "emb": vec_bytes},
        )


def downgrade():
    op.execute("DROP TABLE IF EXISTS article_embeddings_norm")
