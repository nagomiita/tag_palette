"""SQLite initialization and CRUD for novel processing."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS novels (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    author      TEXT,
    url         TEXT,
    description TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS novel_tags (
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    tag_id   INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (novel_id, tag_id)
);

CREATE TABLE IF NOT EXISTS novel_chunks (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    seq      INTEGER NOT NULL,
    kind     TEXT NOT NULL CHECK (kind IN ('dialogue', 'thought', 'narrative')),
    body     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS novel_morphemes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    surface TEXT NOT NULL,
    pos     TEXT NOT NULL,
    UNIQUE (surface, pos)
);

CREATE TABLE IF NOT EXISTS novel_chunk_morphemes (
    chunk_id    INTEGER NOT NULL REFERENCES novel_chunks(id),
    morpheme_id INTEGER NOT NULL REFERENCES novel_morphemes(id),
    count       INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (chunk_id, morpheme_id)
);

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id   INTEGER PRIMARY KEY REFERENCES novel_chunks(id),
    embedding  BLOB NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS routes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id           INTEGER NOT NULL REFERENCES novels(id),
    name               TEXT NOT NULL,
    description        TEXT,
    fork_from_chunk_id INTEGER NOT NULL REFERENCES novel_chunks(id),
    merge_to_chunk_id  INTEGER REFERENCES novel_chunks(id),
    created_at         TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS route_chunks (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id INTEGER NOT NULL REFERENCES routes(id),
    seq      INTEGER NOT NULL,
    kind     TEXT NOT NULL CHECK (kind IN ('dialogue', 'thought', 'narrative')),
    body     TEXT NOT NULL
);

"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Create a connection and initialize schema."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def insert_novel(
    conn: sqlite3.Connection,
    *,
    novel_id: int,
    title: str,
    author: str | None = None,
    url: str | None = None,
    description: str | None = None,
) -> int:
    """Insert a novel. Returns the novel id."""
    conn.execute(
        "INSERT OR IGNORE INTO novels (id, title, author, url, description) VALUES (?, ?, ?, ?, ?)",
        (novel_id, title, author, url, description),
    )
    conn.commit()
    return novel_id


def insert_tags(conn: sqlite3.Connection, novel_id: int, tag_names: list[str]) -> None:
    """Insert tags and link them to a novel."""
    for name in tag_names:
        name = name.strip()
        if not name:
            continue
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO novel_tags (novel_id, tag_id) VALUES (?, ?)",
            (novel_id, row[0]),
        )
    conn.commit()


def insert_chunks(
    conn: sqlite3.Connection,
    novel_id: int,
    chunks: list[tuple[int, str, str]],
) -> list[int]:
    """Insert chunks and return their ids.

    chunks: list of (seq, kind, body)
    """
    chunk_ids = []
    for seq, kind, body in chunks:
        cur = conn.execute(
            "INSERT INTO novel_chunks (novel_id, seq, kind, body) VALUES (?, ?, ?, ?)",
            (novel_id, seq, kind, body),
        )
        chunk_ids.append(cur.lastrowid)
    conn.commit()
    return chunk_ids


def insert_morphemes(
    conn: sqlite3.Connection,
    chunk_id: int,
    morpheme_counts: dict[tuple[str, str], int],
) -> None:
    """Insert morphemes and link them to a chunk.

    morpheme_counts: {(surface, pos): count}
    """
    for (surface, pos), count in morpheme_counts.items():
        conn.execute(
            "INSERT OR IGNORE INTO novel_morphemes (surface, pos) VALUES (?, ?)",
            (surface, pos),
        )
        row = conn.execute(
            "SELECT id FROM novel_morphemes WHERE surface = ? AND pos = ?",
            (surface, pos),
        ).fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO novel_chunk_morphemes (chunk_id, morpheme_id, count) VALUES (?, ?, ?)",
            (chunk_id, row[0], count),
        )
    conn.commit()
