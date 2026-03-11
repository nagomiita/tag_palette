"""Chunk embedding generation, storage, and similarity search."""

from __future__ import annotations

import sqlite3

import numpy as np
from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None
_MODEL_NAME = "intfloat/multilingual-e5-small"


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def generate_embedding(text: str) -> np.ndarray:
    """Generate an embedding vector for the given text."""
    model = _get_model()
    return model.encode(text, normalize_embeddings=True)


def save_embedding(
    conn: sqlite3.Connection,
    chunk_id: int,
    embedding: np.ndarray,
    model_name: str = _MODEL_NAME,
    *,
    table: str = "chunk_embeddings",
) -> None:
    """Save an embedding to the database."""
    blob = embedding.astype(np.float32).tobytes()
    conn.execute(
        f"INSERT OR REPLACE INTO {table} (chunk_id, embedding, model) VALUES (?, ?, ?)",
        (chunk_id, blob, model_name),
    )
    conn.commit()


def load_embedding(
    conn: sqlite3.Connection,
    chunk_id: int,
    *,
    table: str = "chunk_embeddings",
) -> np.ndarray | None:
    """Load an embedding from the database."""
    row = conn.execute(
        f"SELECT embedding FROM {table} WHERE chunk_id = ?", (chunk_id,)
    ).fetchone()
    if row is None:
        return None
    return np.frombuffer(row[0], dtype=np.float32)


def load_all_embeddings(
    conn: sqlite3.Connection,
    novel_id: int | None = None,
    *,
    table: str = "chunk_embeddings",
    chunk_table: str = "novel_chunks",
) -> list[tuple[int, np.ndarray]]:
    """Load all embeddings, optionally filtered by novel_id.

    Returns list of (chunk_id, embedding).
    """
    if novel_id is not None:
        rows = conn.execute(
            f"""
            SELECT e.chunk_id, e.embedding FROM {table} e
            JOIN {chunk_table} c ON c.id = e.chunk_id
            WHERE c.novel_id = ?
            """,
            (novel_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT chunk_id, embedding FROM {table}"
        ).fetchall()

    return [(r[0], np.frombuffer(r[1], dtype=np.float32)) for r in rows]


def search_similar(
    conn: sqlite3.Connection,
    chunk_id: int,
    top_n: int = 10,
    novel_id: int | None = None,
) -> list[tuple[int, float]]:
    """Find similar chunks by cosine similarity.

    Returns list of (chunk_id, similarity) sorted descending.
    Excludes the query chunk itself.
    """
    query_emb = load_embedding(conn, chunk_id)
    if query_emb is None:
        return []

    all_embs = load_all_embeddings(conn, novel_id)
    results = []
    for cid, emb in all_embs:
        if cid == chunk_id:
            continue
        sim = float(np.dot(query_emb, emb))
        results.append((cid, sim))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_n]


def embed_chunks(
    conn: sqlite3.Connection,
    novel_id: int | None = None,
) -> int:
    """Generate and save embeddings for all chunks that don't have one yet.

    Returns number of newly embedded chunks.
    """
    if novel_id is not None:
        rows = conn.execute(
            """
            SELECT c.id, c.body FROM novel_chunks c
            LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id
            WHERE c.novel_id = ? AND e.chunk_id IS NULL
            """,
            (novel_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT c.id, c.body FROM novel_chunks c
            LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id
            WHERE e.chunk_id IS NULL
            """
        ).fetchall()

    if not rows:
        return 0

    model = _get_model()
    texts = [r[1] for r in rows]
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=True)

    for (chunk_id, _), emb in zip(rows, embeddings):
        blob = emb.astype(np.float32).tobytes()
        conn.execute(
            "INSERT OR REPLACE INTO chunk_embeddings (chunk_id, embedding, model) VALUES (?, ?, ?)",
            (chunk_id, blob, _MODEL_NAME),
        )
    conn.commit()
    return len(rows)
