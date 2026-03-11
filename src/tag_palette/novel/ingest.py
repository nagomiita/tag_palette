"""Integration entry point: file parsing -> chunking -> morpheme analysis -> DB."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .chunker import chunk_text
from .db import connect, insert_chunks, insert_morphemes, insert_novel, insert_tags
from .morpheme import extract_morphemes


def parse_novel_file(file_path: Path) -> dict:
    """Parse a novel text file and return metadata + body.

    File name format: {id}_{title}.txt
    File structure:
        Line 1: URL
        Line 2: (blank)
        Line 3: Author
        Line 4: (blank)
        Line 5: Title
        Line 6: (blank)
        Line 7: Tags: tag1, tag2, ...
        Line 8: (blank)
        Line 9+: Body
    """
    stem = file_path.stem
    novel_id = int(stem.split("_", 1)[0])
    title = stem.split("_", 1)[1]

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


def ingest_file(conn: sqlite3.Connection, file_path: Path) -> dict:
    """Process a single novel file: parse, chunk, analyze, store.

    Returns summary stats.
    """
    data = parse_novel_file(file_path)

    # Insert novel
    insert_novel(
        conn,
        novel_id=data["novel_id"],
        title=data["title"],
        author=data["author"],
        url=data["url"],
    )

    # Insert tags
    insert_tags(conn, data["novel_id"], data["tags"])

    # Chunk the body
    chunks = chunk_text(data["body"])
    chunk_tuples = [(c.seq, c.kind, c.body) for c in chunks]
    chunk_ids = insert_chunks(conn, data["novel_id"], chunk_tuples)

    # Morpheme analysis per chunk
    total_morphemes = 0
    for chunk, chunk_id in zip(chunks, chunk_ids):
        morpheme_counts = extract_morphemes(chunk.body)
        insert_morphemes(conn, chunk_id, morpheme_counts)
        total_morphemes += len(morpheme_counts)

    return {
        "novel_id": data["novel_id"],
        "title": data["title"],
        "num_chunks": len(chunks),
        "num_morpheme_types": total_morphemes,
    }


def ingest_directory(db_path: Path, input_dir: Path) -> list[dict]:
    """Process all .txt files in a directory."""
    conn = connect(db_path)
    results = []
    for f in sorted(input_dir.glob("*.txt")):
        result = ingest_file(conn, f)
        results.append(result)
    conn.close()
    return results
