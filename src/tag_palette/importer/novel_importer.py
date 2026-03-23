"""小説エントリの DB 書き込み。"""

from __future__ import annotations

import logging
import sqlite3
import uuid

from .models import NovelPaletteEntry
from .utils import BATCH_SIZE, _chunked

logger = logging.getLogger(__name__)


def _new_uuid() -> str:
    return uuid.uuid4().hex


def _ensure_label(
    conn: sqlite3.Connection,
    cache: dict[str, str],
    name: str,
) -> str:
    """novel_labels を get or create し、ID を返す。"""
    if name in cache:
        return cache[name]
    row = conn.execute(
        "SELECT id FROM novel_labels WHERE name = ?", (name,)
    ).fetchone()
    if row:
        cache[name] = row[0]
        return row[0]
    label_id = _new_uuid()
    conn.execute(
        "INSERT INTO novel_labels (id, name) VALUES (?, ?)",
        (label_id, name),
    )
    cache[name] = label_id
    return label_id


def _ensure_morpheme(
    conn: sqlite3.Connection,
    cache: dict[tuple[str, str], str],
    surface: str,
    pos: str,
) -> str:
    """novel_morphemes を get or create し、ID を返す。"""
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
    morph_id = _new_uuid()
    conn.execute(
        "INSERT INTO novel_morphemes (id, surface, pos) VALUES (?, ?, ?)",
        (morph_id, surface, pos),
    )
    cache[key] = morph_id
    return morph_id


def _auto_label_from_master(
    conn: sqlite3.Connection, title: str, body: str,
) -> list[str]:
    """既存の novel_labels をタイトル+本文から部分一致で自動付与する。"""
    rows = conn.execute(
        "SELECT name FROM novel_labels ORDER BY length(name) DESC"
    ).fetchall()
    text = title + "\n" + body
    return [name for (name,) in rows if len(name) >= 2 and name in text]


def import_novel_entries(
    conn: sqlite3.Connection,
    entries: list[NovelPaletteEntry],
) -> dict[str, int]:
    """小説エントリを novels / novel_chunks / novel_labels / novel_morphemes テーブルに書き込む。

    ingest_local.py と同等のロジック:
    - UUID ベースの ID 生成
    - 形態素解析 (extract_morphemes)
    - 自動ラベル付与 (_auto_label_from_master)
    """
    from tag_palette.novel.morpheme import extract_morphemes

    stats = {
        "novels_created": 0,
        "novels_skipped": 0,
        "chunks_created": 0,
        "morphemes_created": 0,
        "labels_linked": 0,
    }

    # 既存 novels を一括取得
    all_ids = [e.novel_id for e in entries]
    existing_novels: set[str] = set()
    for batch in _chunked(all_ids, BATCH_SIZE):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"SELECT id FROM novels WHERE id IN ({placeholders})", batch
        ).fetchall()
        existing_novels.update(r[0] for r in rows)

    label_cache: dict[str, str] = {}
    morph_cache: dict[tuple[str, str], str] = {}

    for i, entry in enumerate(entries):
        novel_id = entry.novel_id

        # 既存ならスキップ (ingest_local.py と同じ方針)
        if novel_id in existing_novels:
            stats["novels_skipped"] += 1
            continue

        # 1. novels INSERT
        conn.execute(
            "INSERT INTO novels (id, title, author, url, is_sensitive) VALUES (?, ?, ?, ?, ?)",
            (novel_id, entry.title, entry.author, entry.url, entry.is_sensitive),
        )
        existing_novels.add(novel_id)
        stats["novels_created"] += 1

        # 2. ラベル (タグ) の紐付け
        tag_names = list(entry.tags)
        if not tag_names and entry.chunks:
            # タグが無い場合は自動ラベル付与
            full_body = "\n".join(c.get("body", "") for c in entry.chunks)
            tag_names = _auto_label_from_master(conn, entry.title, full_body)
            if tag_names:
                logger.info("  自動ラベル: %s", ", ".join(tag_names[:10]))

        for tag_name in tag_names:
            tag_name = tag_name.strip()
            if not tag_name:
                continue
            label_id = _ensure_label(conn, label_cache, tag_name)
            assoc_id = _new_uuid()
            conn.execute(
                "INSERT OR IGNORE INTO novel_label_associations (id, novel_id, label_id) "
                "VALUES (?, ?, ?)",
                (assoc_id, novel_id, label_id),
            )
            stats["labels_linked"] += 1

        # 3. チャンク + 形態素
        cm_batch: list[tuple] = []
        for chunk in entry.chunks:
            chunk_id = _new_uuid()
            seq = chunk.get("seq", 0)
            kind = chunk.get("kind", "narrative")
            body = chunk.get("body", "")

            conn.execute(
                "INSERT INTO novel_chunks (id, novel_id, seq, kind, body) VALUES (?, ?, ?, ?, ?)",
                (chunk_id, novel_id, seq, kind, body),
            )
            stats["chunks_created"] += 1

            # 形態素解析
            morpheme_counts = extract_morphemes(body)
            for (surface, pos), count in morpheme_counts.items():
                morph_id = _ensure_morpheme(conn, morph_cache, surface, pos)
                cm_batch.append((_new_uuid(), chunk_id, morph_id, count))
            stats["morphemes_created"] += len(morpheme_counts)

            if len(cm_batch) >= BATCH_SIZE:
                conn.executemany(
                    "INSERT INTO novel_chunk_morphemes (id, chunk_id, morpheme_id, count) "
                    "VALUES (?, ?, ?, ?)",
                    cm_batch,
                )
                cm_batch.clear()

        if cm_batch:
            conn.executemany(
                "INSERT INTO novel_chunk_morphemes (id, chunk_id, morpheme_id, count) "
                "VALUES (?, ?, ?, ?)",
                cm_batch,
            )

        if (i + 1) % 10 == 0:
            conn.commit()
            logger.info("小説インポート: %d / %d 件", i + 1, len(entries))

    conn.commit()
    return stats
