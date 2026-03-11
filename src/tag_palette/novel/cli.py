"""CLI entry point for novel ingestion."""

from __future__ import annotations

import sys
from pathlib import Path

from .ingest import ingest_directory


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m tag_palette.novel.cli <input_dir> [db_path]")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/novel.db")

    db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Input: {input_dir}")
    print(f"DB:    {db_path}")
    print()

    results = ingest_directory(db_path, input_dir)

    for r in results:
        print(f"  [{r['novel_id']}] {r['title']} - {r['num_chunks']} chunks, {r['num_morpheme_types']} morpheme types")

    print(f"\nDone: {len(results)} novels ingested into {db_path}")


if __name__ == "__main__":
    main()
