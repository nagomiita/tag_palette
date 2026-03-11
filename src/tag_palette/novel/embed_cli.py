"""CLI for batch embedding generation."""

from __future__ import annotations

import sys
from pathlib import Path

from .db import connect
from .embedding import embed_chunks


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m tag_palette.novel.embed_cli <db_path> [novel_id]")
        print()
        print("  db_path   : SQLite DB path (e.g. data/novel.db)")
        print("  novel_id  : (optional) specific novel ID to embed")
        sys.exit(1)

    db_path = Path(sys.argv[1])
    novel_id = int(sys.argv[2]) if len(sys.argv) > 2 else None

    if not db_path.exists():
        print(f"Error: {db_path} not found")
        sys.exit(1)

    conn = connect(db_path)

    # Show stats before
    total = conn.execute("SELECT COUNT(*) FROM novel_chunks").fetchone()[0]
    existing = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
    pending = total - existing

    if novel_id is not None:
        novel_total = conn.execute(
            "SELECT COUNT(*) FROM novel_chunks WHERE novel_id = ?", (novel_id,)
        ).fetchone()[0]
        novel_existing = conn.execute(
            """
            SELECT COUNT(*) FROM chunk_embeddings e
            JOIN novel_chunks c ON c.id = e.chunk_id
            WHERE c.novel_id = ?
            """,
            (novel_id,),
        ).fetchone()[0]
        print(f"DB: {db_path}")
        print(f"Novel {novel_id}: {novel_total} chunks, {novel_existing} embedded, {novel_total - novel_existing} pending")
    else:
        print(f"DB: {db_path}")
        print(f"All: {total} chunks, {existing} embedded, {pending} pending")

    print()
    count = embed_chunks(conn, novel_id=novel_id)
    print(f"\nDone: {count} chunks embedded")

    conn.close()


if __name__ == "__main__":
    main()
