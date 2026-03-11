"""Ingest novel text files into the production local.db (UUID-based schema).

Usage:
    python src/tag_palette/novel/ingest_local.py [input_dir] [--db <path>] [--dry-run]

Reads NOVELS_DIR and SQLITE_DB_PATH from .env (dotenv).
CLI arguments override .env values.

File name format: {pixiv_id}_{title}.txt
File structure:
    Line 1: URL
    Line 3: Author
    Line 5: Title
    Line 7: Tags: tag1, tag2, ...
    Line 9+: Body
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

from .chunker import chunk_text
from .morpheme import extract_morphemes

# Load .env from project root
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_ENV_PATH)


def _env_path(key: str) -> Path | None:
    val = os.getenv(key)
    if val:
        return Path(val)
    return None

BATCH_SIZE = 500


def _new_id() -> str:
    return uuid.uuid4().hex


def _parse_novel_file(file_path: Path) -> dict:
    """Parse a novel text file and return metadata + body."""
    stem = file_path.stem
    novel_id = stem.split("_", 1)[0]  # Pixiv ID as string
    title = stem.split("_", 1)[1] if "_" in stem else stem

    text = file_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    url = lines[0].strip() if len(lines) > 0 else ""
    author = lines[2].strip() if len(lines) > 2 else ""
    tag_line = lines[6].strip() if len(lines) > 6 else ""

    tags: list[str] = []
    if tag_line.startswith("Tags:"):
        tags = [t.strip() for t in tag_line[5:].split(",") if t.strip()]

    body = "\n".join(lines[8:])

    return {
        "novel_id": novel_id,
        "title": title,
        "author": author,
        "url": url,
        "tags": tags,
        "body": body,
    }


def _ensure_label(conn: sqlite3.Connection, name: str) -> str:
    """Get or create a novel_label, return its id."""
    row = conn.execute(
        "SELECT id FROM novel_labels WHERE name = ?", (name,)
    ).fetchone()
    if row:
        return row[0]
    label_id = _new_id()
    conn.execute(
        "INSERT INTO novel_labels (id, name) VALUES (?, ?)",
        (label_id, name),
    )
    return label_id


def _ensure_morpheme(
    conn: sqlite3.Connection,
    cache: dict[tuple[str, str], str],
    surface: str,
    pos: str,
) -> str:
    """Get or create a novel_morpheme, return its id. Uses in-memory cache."""
    key = (surface, pos)
    if key in cache:
        return cache[key]
    row = conn.execute(
        "SELECT id FROM novel_morphemes WHERE surface = ? AND pos = ?",
        (surface, pos),
    ).fetchone()
    if row:
        cache[key] = row[0]
        return row[0]
    morph_id = _new_id()
    conn.execute(
        "INSERT INTO novel_morphemes (id, surface, pos) VALUES (?, ?, ?)",
        (morph_id, surface, pos),
    )
    cache[key] = morph_id
    return morph_id


def ingest_file(conn: sqlite3.Connection, file_path: Path, morph_cache: dict) -> dict:
    """Process a single novel file into the production DB.

    Returns summary stats.
    """
    data = _parse_novel_file(file_path)
    novel_id = data["novel_id"]

    # Skip if already exists
    existing = conn.execute(
        "SELECT id FROM novels WHERE id = ?", (novel_id,)
    ).fetchone()
    if existing:
        return {
            "novel_id": novel_id,
            "title": data["title"],
            "skipped": True,
        }

    # 1. Insert novel (id = Pixiv ID as string)
    conn.execute(
        "INSERT INTO novels (id, title, author, url) VALUES (?, ?, ?, ?)",
        (novel_id, data["title"], data["author"], data["url"]),
    )

    # 2. Labels (tags)
    for tag_name in data["tags"]:
        tag_name = tag_name.strip()
        if not tag_name:
            continue
        label_id = _ensure_label(conn, tag_name)
        assoc_id = _new_id()
        conn.execute(
            "INSERT OR IGNORE INTO novel_label_associations (id, novel_id, label_id) VALUES (?, ?, ?)",
            (assoc_id, novel_id, label_id),
        )

    # 3. Chunks
    chunks = chunk_text(data["body"])
    chunk_ids: list[str] = []
    for c in chunks:
        chunk_id = _new_id()
        chunk_ids.append(chunk_id)
        conn.execute(
            "INSERT INTO novel_chunks (id, novel_id, seq, kind, body) VALUES (?, ?, ?, ?, ?)",
            (chunk_id, novel_id, c.seq, c.kind, c.body),
        )

    # 4. Morphemes per chunk
    total_morphemes = 0
    cm_batch: list[tuple] = []
    for chunk, chunk_id in zip(chunks, chunk_ids):
        morpheme_counts = extract_morphemes(chunk.body)
        for (surface, pos), count in morpheme_counts.items():
            morph_id = _ensure_morpheme(conn, morph_cache, surface, pos)
            cm_batch.append((_new_id(), chunk_id, morph_id, count))
        total_morphemes += len(morpheme_counts)

        if len(cm_batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT INTO novel_chunk_morphemes (id, chunk_id, morpheme_id, count) VALUES (?, ?, ?, ?)",
                cm_batch,
            )
            cm_batch.clear()

    if cm_batch:
        conn.executemany(
            "INSERT INTO novel_chunk_morphemes (id, chunk_id, morpheme_id, count) VALUES (?, ?, ?, ?)",
            cm_batch,
        )

    conn.commit()

    return {
        "novel_id": novel_id,
        "title": data["title"],
        "num_chunks": len(chunks),
        "num_morpheme_types": total_morphemes,
        "skipped": False,
    }


def ingest_directory(db_path: Path, input_dir: Path, *, dry_run: bool = False) -> list[dict]:
    """Process all .txt files in a directory into the production DB."""
    files = sorted(input_dir.glob("*.txt"))
    print(f"Input: {input_dir}")
    print(f"DB:    {db_path}")
    print(f"Files: {len(files)}")

    if dry_run:
        for f in files:
            stem = f.stem
            novel_id = stem.split("_", 1)[0]
            title = stem.split("_", 1)[1] if "_" in stem else stem
            print(f"  [{novel_id}] {title}")
        print(f"\n--dry-run: {len(files)} files found, no data written.")
        return []

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    morph_cache: dict[tuple[str, str], str] = {}
    results = []
    for i, f in enumerate(files, 1):
        result = ingest_file(conn, f, morph_cache)
        if result.get("skipped"):
            print(f"  [{i}/{len(files)}] SKIP {result['novel_id']} {result['title']}")
        else:
            print(
                f"  [{i}/{len(files)}] {result['novel_id']} {result['title']}"
                f" - {result['num_chunks']} chunks, {result['num_morpheme_types']} morphemes"
            )
        results.append(result)

    conn.close()

    ingested = sum(1 for r in results if not r.get("skipped"))
    skipped = sum(1 for r in results if r.get("skipped"))
    print(f"\nDone: {ingested} ingested, {skipped} skipped.")
    return results


def main() -> None:
    env_novels_dir = _env_path("NOVELS_DIR")
    env_db_path = _env_path("SQLITE_DB_PATH")

    parser = argparse.ArgumentParser(description="Ingest novel files into production local.db")
    parser.add_argument(
        "input_dir", type=Path, nargs="?", default=env_novels_dir,
        help="Directory containing {id}_{title}.txt files (default: NOVELS_DIR from .env)",
    )
    parser.add_argument(
        "--db", type=Path, default=env_db_path,
        help="Destination DB path (default: SQLITE_DB_PATH from .env)",
    )
    parser.add_argument("--dry-run", action="store_true", help="List files only, do not write")
    args = parser.parse_args()

    if args.input_dir is None:
        print("Error: input_dir not specified and NOVELS_DIR not set in .env", file=sys.stderr)
        sys.exit(1)
    if args.db is None:
        print("Error: --db not specified and SQLITE_DB_PATH not set in .env", file=sys.stderr)
        sys.exit(1)
    if not args.input_dir.is_dir():
        print(f"Not a directory: {args.input_dir}", file=sys.stderr)
        sys.exit(1)
    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    ingest_directory(args.db, args.input_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
