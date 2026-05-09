"""メディア (画像/動画/HTML) の DB 書き込み。"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid

import numpy as np

from .csv_loader import match_category_rule
from .models import (
    CategoryEntry,
    CategoryRule,
    DanbooruTag,
    GenreEntry,
    TagPaletteEntry,
)
from .utils import BATCH_SIZE, _chunked, _now_iso

logger = logging.getLogger(__name__)

# Danbooru category code → DB category name
DANBOORU_CATEGORY_MAP: dict[str, str] = {
    "0": "general",
    "3": "copyright",
    "4": "character",
}

_VIDEO_EXTENSIONS = {
    "mp4", "webm", "mkv", "avi", "mov", "wmv", "flv", "m4v", "mpg", "mpeg",
}
_COMIC_TAGS = {"comic", "greyscale", "monochrome", "speech_bubble"}

_HTML_EXTENSIONS = {"html", "htm"}


def _detect_media_type(ext: str, tags: dict[str, float] | None = None) -> str:
    if ext.lower().strip(".") in _VIDEO_EXTENSIONS:
        return "VIDEO"
    if ext.lower().strip(".") in _HTML_EXTENSIONS:
        return "HTML"
    if tags and _COMIC_TAGS & tags.keys():
        return "MANGA"
    return "IMAGE"


def sync_master_data(
    conn: sqlite3.Connection,
    danbooru: dict[str, DanbooruTag],
    genres: dict[str, GenreEntry],
    categories: dict[str, CategoryEntry],
    trans_cache: dict[str, str],
    entry_tags: set[str],
    category_rules: list[CategoryRule] | None = None,
) -> None:
    """カテゴリ・ジャンル・タグ・タグジャンルを SQLite に直接書き込む。"""
    now = _now_iso()

    # 既存タグの name を読み込み（DB の値を優先するため）
    existing_tag_names: dict[str, str] = {}
    for row in conn.execute("SELECT id, name FROM tags WHERE name IS NOT NULL"):
        existing_tag_names[row[0]] = row[1]

    # ── 1. カテゴリ ──────────────────────────────────────────
    for cat in categories.values():
        conn.execute(
            "INSERT INTO categories (id, name, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            (cat.id, cat.name, now),
        )
    logger.info("カテゴリ同期: %d 件", len(categories))

    # カテゴリコード → ID マッピング
    cat_code_to_id: dict[str, str] = {}
    for code, csv_name in DANBOORU_CATEGORY_MAP.items():
        if csv_name in categories:
            cat_code_to_id[code] = categories[csv_name].id

    # ── 2. ジャンル ──────────────────────────────────────────
    for g in genres.values():
        conn.execute(
            "INSERT INTO genres (id, name, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            (g.key, g.ja or g.key, now),
        )
    logger.info("ジャンル同期: %d 件", len(genres))

    # ── 3. タグ ──────────────────────────────────────────────
    tag_count = 0
    tag_genre_data: list[tuple[str, str, str]] = []
    seen_tag_ids: set[str] = set()

    def _resolve_name(tag_en: str, csv_name: str) -> str:
        return existing_tag_names.get(tag_en, csv_name)

    # 3a. danbooru_tags
    rule_overrides = 0
    for tag_en, db_tag in danbooru.items():
        category_id = cat_code_to_id.get(db_tag.category)
        if db_tag.category == "0" and category_rules:
            matched = match_category_rule(tag_en, category_rules)
            if matched and matched in categories:
                category_id = matched
                rule_overrides += 1
        tag_ja = _resolve_name(tag_en, db_tag.ja or tag_en)
        conn.execute(
            "INSERT INTO tags (id, name, category_id, is_favorite, disable, created_at) VALUES (?, ?, ?, 0, 0, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, category_id = excluded.category_id",
            (tag_en, tag_ja, category_id, now),
        )
        tag_count += 1
        seen_tag_ids.add(tag_en)

        if db_tag.genre and db_tag.genre in genres:
            tag_genre_data.append((f"{tag_en}__{db_tag.genre}", tag_en, db_tag.genre))

    # 3b. translation_cache（danbooru にないもの）
    for tag_en, tag_ja in trans_cache.items():
        if tag_en not in seen_tag_ids:
            conn.execute(
                "INSERT INTO tags (id, name, is_favorite, disable, created_at) VALUES (?, ?, 0, 0, ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
                (tag_en, _resolve_name(tag_en, tag_ja), now),
            )
            tag_count += 1
            seen_tag_ids.add(tag_en)

    # 3c. entry にあるが danbooru/translation_cache にないタグ
    for tag_en in entry_tags:
        if tag_en not in seen_tag_ids:
            conn.execute(
                "INSERT INTO tags (id, name, is_favorite, disable, created_at) VALUES (?, ?, 0, 0, ?) "
                "ON CONFLICT(id) DO NOTHING",
                (tag_en, _resolve_name(tag_en, tag_en), now),
            )
            tag_count += 1
            seen_tag_ids.add(tag_en)

    if rule_overrides:
        logger.info("カテゴリルール上書き: %d 件", rule_overrides)
    logger.info("タグ同期: %d 件", tag_count)

    # ── 4. タグジャンル ──────────────────────────────────────
    for tg_id, tag_id, genre_id in tag_genre_data:
        conn.execute(
            "INSERT INTO tag_genres (id, tag_id, genre_id, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO NOTHING",
            (tg_id, tag_id, genre_id, now),
        )
    if tag_genre_data:
        logger.info("タグジャンル同期: %d 件", len(tag_genre_data))

    conn.commit()


def import_entries(
    conn: sqlite3.Connection,
    entries: list[TagPaletteEntry],
) -> dict[str, int]:
    """tag_palette エントリを SQLite に直接書き込む。"""
    now = _now_iso()
    stats = {
        "media_created": 0,
        "media_updated": 0,
        "media_tags_created": 0,
        "tags_auto_created": 0,
    }

    # 既存 media ID を一括取得
    all_ids = [e.image_id for e in entries]
    existing_media: set[str] = set()
    for batch in _chunked(all_ids, BATCH_SIZE):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(f"SELECT id FROM media WHERE id IN ({placeholders})", batch).fetchall()
        existing_media.update(r[0] for r in rows)

    # 既存タグ ID を一括取得
    all_tag_ids: set[str] = set()
    for e in entries:
        all_tag_ids.update(e.tags.keys())
    existing_tag_ids: set[str] = set()
    for batch in _chunked(list(all_tag_ids), BATCH_SIZE):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(f"SELECT id FROM tags WHERE id IN ({placeholders})", batch).fetchall()
        existing_tag_ids.update(r[0] for r in rows)

    # 既存 embedding media_id を一括取得
    existing_emb: set[str] = set()
    for batch in _chunked(all_ids, BATCH_SIZE):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(f"SELECT media_id FROM media_embeddings WHERE media_id IN ({placeholders})", batch).fetchall()
        existing_emb.update(r[0] for r in rows)

    for i, entry in enumerate(entries):
        media_id = entry.image_id
        file_path = f"images/{entry.image_id}.info/{entry.image_name}"
        thumbnail_path = f"images/{entry.image_id}.info/{entry.thumbnail_name}"
        media_type = _detect_media_type(entry.ext, entry.tags)

        # ── 1. Media UPSERT ───────────────────────────────
        classify_json = json.dumps(entry.classify_scores) if entry.classify_scores else None
        completeness_json = json.dumps(entry.completeness_scores) if entry.completeness_scores else None
        portrait_json = json.dumps(entry.portrait_scores) if entry.portrait_scores else None

        if media_id in existing_media:
            if entry.ai_score is not None:
                conn.execute(
                    "UPDATE media SET ai_score = ? WHERE id = ? AND ai_score IS NULL",
                    (entry.ai_score, media_id),
                )
            if entry.real_score is not None:
                conn.execute(
                    "UPDATE media SET real_score = ? WHERE id = ? AND real_score IS NULL",
                    (entry.real_score, media_id),
                )
            if entry.monochrome_score is not None:
                conn.execute(
                    "UPDATE media SET monochrome_score = ? WHERE id = ? AND monochrome_score IS NULL",
                    (entry.monochrome_score, media_id),
                )
            if classify_json is not None:
                conn.execute(
                    "UPDATE media SET classify_scores = ? WHERE id = ? AND classify_scores IS NULL",
                    (classify_json, media_id),
                )
            if completeness_json is not None:
                conn.execute(
                    "UPDATE media SET completeness_scores = ? WHERE id = ? AND completeness_scores IS NULL",
                    (completeness_json, media_id),
                )
            if portrait_json is not None:
                conn.execute(
                    "UPDATE media SET portrait_scores = ? WHERE id = ? AND portrait_scores IS NULL",
                    (portrait_json, media_id),
                )
            if entry.ocr_text is not None:
                conn.execute(
                    "UPDATE media SET ocr_text = ? WHERE id = ? AND ocr_text IS NULL",
                    (entry.ocr_text, media_id),
                )
            conn.execute(
                "UPDATE media SET media_type = ? WHERE id = ? AND media_type IS NULL",
                (media_type, media_id),
            )
            if entry.genre is not None:
                conn.execute(
                    "UPDATE media SET genre_id = ? WHERE id = ? AND genre_id IS NULL",
                    (entry.genre, media_id),
                )
            conn.execute(
                "UPDATE media SET is_sensitive = ? WHERE id = ? AND is_sensitive IS NULL",
                (entry.is_sensitive, media_id),
            )
            stats["media_updated"] += 1
        else:
            try:
                conn.execute(
                    "INSERT INTO media (id, file_path, file_name, file_extension, thumbnail_path, "
                    "is_sensitive, ai_score, real_score, monochrome_score, classify_scores, completeness_scores, "
                    "portrait_scores, media_type, genre_id, ocr_text, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (media_id, file_path, entry.image_name, entry.ext, thumbnail_path,
                     entry.is_sensitive, entry.ai_score, entry.real_score,
                     entry.monochrome_score, classify_json, completeness_json, portrait_json,
                     media_type, entry.genre, entry.ocr_text, now),
                )
            except sqlite3.IntegrityError:
                existing = conn.execute(
                    "SELECT id FROM media WHERE file_path = ?", (file_path,)
                ).fetchone()
                existing_id = existing[0] if existing else "?"
                logger.error(
                    "file_path 重複: new_id=%s existing_id=%s path=%s",
                    media_id, existing_id, file_path,
                )
                raise
            existing_media.add(media_id)
            stats["media_created"] += 1

        # ── 2. MediaTags UPSERT ───────────────────────────
        for tag_id, confidence in entry.tags.items():
            if tag_id not in existing_tag_ids:
                conn.execute(
                    "INSERT INTO tags (id, name, is_favorite, disable, created_at) VALUES (?, ?, 0, 0, ?) ON CONFLICT(id) DO NOTHING",
                    (tag_id, tag_id, now),
                )
                existing_tag_ids.add(tag_id)
                stats["tags_auto_created"] += 1

            mt_id = f"{media_id}__{tag_id}__{entry.model_name}"
            conn.execute(
                "INSERT INTO media_tags (id, media_id, tag_id, confidence, model_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET confidence = excluded.confidence",
                (mt_id, media_id, tag_id, confidence, entry.model_name, now),
            )
            stats["media_tags_created"] += 1

        # ── 3. MediaEmbedding UPSERT ──────────────────────
        if entry.tag_embedding or entry.ccip_embedding or entry.pose_embedding:
            if media_id in existing_emb:
                if entry.tag_embedding:
                    conn.execute(
                        "UPDATE media_embeddings SET tag_embedding = ? WHERE media_id = ? AND tag_embedding IS NULL",
                        (entry.tag_embedding, media_id),
                    )
                if entry.ccip_embedding:
                    conn.execute(
                        "UPDATE media_embeddings SET ccip_embedding = ? WHERE media_id = ? AND ccip_embedding IS NULL",
                        (entry.ccip_embedding, media_id),
                    )
                if entry.pose_embedding:
                    conn.execute(
                        "UPDATE media_embeddings SET pose_embedding = ? WHERE media_id = ? AND pose_embedding IS NULL",
                        (entry.pose_embedding, media_id),
                    )
            else:
                conn.execute(
                    "INSERT INTO media_embeddings (media_id, tag_embedding, ccip_embedding, pose_embedding) VALUES (?, ?, ?, ?)",
                    (media_id, entry.tag_embedding, entry.ccip_embedding, entry.pose_embedding),
                )
                existing_emb.add(media_id)

        if (i + 1) % 1000 == 0:
            conn.commit()
            logger.info("エントリインポート: %d / %d 件", i + 1, len(entries))

    conn.commit()
    return stats


def sync_tag_embeddings(conn: sqlite3.Connection) -> int:
    """tags テーブルに存在して tag_embeddings に未登録のタグの埋め込みを生成・登録する。"""
    from tag_palette.shared.embedding import (
        _get_tag_embedding,
        load_tag_embeddings,
        save_tag_embeddings,
    )

    load_tag_embeddings()

    # DB に既にある tag_embedding の tag_id
    existing = {
        r[0] for r in conn.execute("SELECT tag_id FROM tag_embeddings").fetchall()
    }
    # tags テーブルの全 ID
    all_tags = {
        r[0] for r in conn.execute("SELECT id FROM tags").fetchall()
    }
    missing = all_tags - existing
    if not missing:
        return 0

    now = _now_iso()
    inserted = 0
    for batch in _chunked(list(missing), BATCH_SIZE):
        for tag_id in batch:
            vec = _get_tag_embedding(tag_id)
            embedding_bytes = np.asarray(vec, dtype=np.float32).tobytes()
            conn.execute(
                "INSERT INTO tag_embeddings (id, tag_id, embedding, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(tag_id) DO NOTHING",
                (uuid.uuid4().hex, tag_id, embedding_bytes, now),
            )
            inserted += 1
        conn.commit()

    if inserted:
        save_tag_embeddings()
        logger.info("タグ埋め込み同期: %d 件追加", inserted)
    return inserted
