"""desc_text / desc_embedding のバックフィル。"""

from __future__ import annotations

import logging
import sqlite3

import numpy as np

logger = logging.getLogger(__name__)

DESC_MODEL = "tag-csv-v1"
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"


def _backfill_desc_text(conn: sqlite3.Connection) -> int:
    """desc_text が NULL のメディアにタグのカンマ区切りを埋める。"""
    media_ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM media WHERE desc_text IS NULL OR desc_text = ''"
        ).fetchall()
    ]
    if not media_ids:
        return 0

    # タグを confidence 降順で一括取得
    placeholders = ",".join("?" for _ in media_ids)
    tag_rows = conn.execute(
        f"""
        SELECT mt.media_id, t.name, mt.confidence
        FROM media_tags mt
        JOIN tags t ON t.id = mt.tag_id
        WHERE mt.media_id IN ({placeholders})
        ORDER BY mt.media_id, mt.confidence DESC
        """,
        media_ids,
    ).fetchall()

    tags_by_media: dict[str, list[str]] = {mid: [] for mid in media_ids}
    for media_id, tag_name, _conf in tag_rows:
        if tag_name:
            tags_by_media[media_id].append(tag_name)

    updated = 0
    for media_id in media_ids:
        tag_list = tags_by_media.get(media_id, [])
        if not tag_list:
            continue
        description = ", ".join(tag_list)
        conn.execute(
            "UPDATE media SET desc_text = ?, desc_model = ? WHERE id = ?",
            (description, DESC_MODEL, media_id),
        )
        updated += 1

    conn.commit()
    return updated


def _backfill_desc_embedding(conn: sqlite3.Connection) -> int:
    """desc_embedding が NULL のメディアに embedding を生成して埋める。"""
    from sentence_transformers import SentenceTransformer

    rows = conn.execute(
        """
        SELECT m.id, m.desc_text
        FROM media m
        JOIN media_embeddings me ON me.media_id = m.id
        WHERE me.desc_embedding IS NULL
          AND m.desc_text IS NOT NULL
          AND m.desc_text != ''
        """
    ).fetchall()

    if not rows:
        return 0

    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    texts = [r[1] for r in rows]
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=len(texts) > 100)

    for (media_id, _), emb in zip(rows, embeddings):
        blob = emb.astype(np.float32).tobytes()
        conn.execute(
            "UPDATE media_embeddings SET desc_embedding = ? WHERE media_id = ?",
            (blob, media_id),
        )
    conn.commit()
    return len(rows)


def post_import_desc(conn: sqlite3.Connection) -> None:
    """インポート後に desc_text と desc_embedding を補完する。"""
    n_desc = _backfill_desc_text(conn)
    if n_desc:
        logger.info("desc_text 生成: %d 件", n_desc)

    n_emb = _backfill_desc_embedding(conn)
    if n_emb:
        logger.info("desc_embedding 生成: %d 件", n_emb)

    if not n_desc and not n_emb:
        logger.info("desc 補完: 対象なし")
