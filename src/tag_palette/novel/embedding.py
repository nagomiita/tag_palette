"""Chunk embedding generation, storage, and similarity search.

Usage (CLI):
    python -m tag_palette.novel.embedding [--db <path>] [--novel-id <id>] [--batch-size <n>]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
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


_DEFAULT_BATCH_SIZE = 1024


def embed_chunks(
    conn: sqlite3.Connection,
    novel_id: str | None = None,
    *,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> int:
    """Generate and save embeddings for all chunks that don't have one yet.

    Processes in batches to avoid memory issues on large datasets.
    Returns number of newly embedded chunks.
    """
    where = "WHERE e.chunk_id IS NULL"
    params: tuple = ()
    if novel_id is not None:
        where = "WHERE c.novel_id = ? AND e.chunk_id IS NULL"
        params = (novel_id,)

    total_pending = conn.execute(
        f"""
        SELECT count(*) FROM novel_chunks c
        LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id
        {where}
        """,
        params,
    ).fetchone()[0]

    if total_pending == 0:
        return 0

    print(f"Pending: {total_pending} chunks")
    model = _get_model()
    total_done = 0

    while True:
        rows = conn.execute(
            f"""
            SELECT c.id, c.body FROM novel_chunks c
            LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id
            {where}
            LIMIT ?
            """,
            (*params, batch_size),
        ).fetchall()

        if not rows:
            break

        texts = [r[1] for r in rows]
        embeddings = model.encode(texts, normalize_embeddings=True)

        for (chunk_id, _), emb in zip(rows, embeddings):
            blob = emb.astype(np.float32).tobytes()
            conn.execute(
                "INSERT OR REPLACE INTO chunk_embeddings (chunk_id, embedding, model) VALUES (?, ?, ?)",
                (chunk_id, blob, _MODEL_NAME),
            )
        conn.commit()

        total_done += len(rows)
        print(f"  {total_done}/{total_pending} embedded")

    return total_done


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def main() -> None:
    load_dotenv(_ENV_PATH)

    parser = argparse.ArgumentParser(
        description="Generate embeddings for novel chunks that don't have one yet.",
    )
    parser.add_argument(
        "--db", type=Path, default=os.getenv("SQLITE_DB_PATH"),
        help="DB path (default: SQLITE_DB_PATH from .env)",
    )
    parser.add_argument(
        "--novel-id", type=str, default=None,
        help="Process only chunks belonging to this novel ID",
    )
    parser.add_argument(
        "--batch-size", type=int, default=_DEFAULT_BATCH_SIZE,
        help=f"Batch size for encoding (default: {_DEFAULT_BATCH_SIZE})",
    )
    args = parser.parse_args()

    if args.db is None:
        print("Error: --db not specified and SQLITE_DB_PATH not set in .env", file=sys.stderr)
        sys.exit(1)
    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA journal_mode=WAL")

    count = embed_chunks(conn, args.novel_id, batch_size=args.batch_size)
    print(f"\nDone: {count} embeddings generated.")
    conn.close()


if __name__ == "__main__":
    main()
