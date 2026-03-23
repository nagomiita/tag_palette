"""Eagle ライブラリの tag_palette.json を SQLite に直接インポートする。

images ディレクトリ内の各 *.info/tag_palette.json を読み取り、
CSV マスタデータ (danbooru_tags / genre / translation_cache) で補完したうえで
SQLite DB に直接書き込む。

Usage:
    uv run python import_to_sqlite.py \
        --image-dir /Volumes/Shared/eagle.library/images
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "src" / "tag_palette" / "data"

# Danbooru category code → DB category name
DANBOORU_CATEGORY_MAP: dict[str, str] = {
    "0": "general",
    "3": "copyright",
    "4": "character",
}

BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# データ構造
# ---------------------------------------------------------------------------


@dataclass
class TagPaletteEntry:
    """tag_palette.json 1件分 (画像/動画)。"""

    image_id: str
    image_name: str
    thumbnail_name: str
    ext: str
    model_name: str
    genre: str | None
    is_sensitive: bool
    ai_score: float | None
    real_score: float | None
    monochrome_score: float | None
    classify_scores: dict[str, float] | None
    completeness_scores: dict[str, float] | None
    portrait_scores: dict[str, float] | None
    tags: dict[str, float]  # {英語タグ: confidence}
    tags_ja: dict[str, str]  # {英語タグ: 日本語名}
    generated_at: str
    info_dir: Path
    tag_embedding: bytes | None  # embedding.npy から読み込んだ生バイト
    ccip_embedding: bytes | None  # ccip_embedding.npy から読み込んだ生バイト
    pose_embedding: bytes | None  # pose_embedding.npy から読み込んだ生バイト


@dataclass
class AudioPaletteEntry:
    """tag_palette.json 1件分 (音声)。"""

    asset_id: str
    file_path: str
    file_name: str
    file_extension: str
    audio_type: str  # "bgm", "se", "voice"
    duration_ms: int | None
    sample_rate: int | None
    file_size: int | None
    description: str | None
    transcript: str | None
    model_name: str
    tags: dict[str, float]
    generated_at: str


@dataclass
class NovelPaletteEntry:
    """tag_palette.json 1件分 (小説)。"""

    novel_id: str
    title: str
    author: str
    url: str
    tags: list[str]  # ラベル名のリスト
    is_sensitive: bool
    num_chunks: int
    num_morphemes: int
    chunks: list[dict]  # [{"seq": int, "kind": str, "body": str}, ...]
    generated_at: str


@dataclass
class DanbooruTag:
    """danbooru_tags.csv 1行分。"""

    tag: str
    category: str  # "0", "3", "4"
    count: int
    genre: str  # genre.csv の key
    ja: str
    memo: str


@dataclass
class CategoryEntry:
    """category.csv 1行分。"""

    id: str
    name: str


@dataclass
class GenreEntry:
    """genre.csv 1行分。"""

    key: str
    count: int
    ja: str


@dataclass
class CategoryRule:
    """tag_category_rules.csv 1行分。"""

    match_type: str  # "prefix", "suffix", "contains"
    pattern: str
    category: str  # category.csv の id
    priority: int


# ---------------------------------------------------------------------------
# CSV 読み込み
# ---------------------------------------------------------------------------


def load_categories(path: Path | None = None) -> dict[str, CategoryEntry]:
    """category.csv → {id: CategoryEntry}"""
    path = path or DATA_DIR / "category.csv"
    result: dict[str, CategoryEntry] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cat_id = row["id"]
            result[cat_id] = CategoryEntry(id=cat_id, name=row.get("name", cat_id))
    logger.info("category.csv: %d 件", len(result))
    return result


def load_danbooru_tags(path: Path | None = None) -> dict[str, DanbooruTag]:
    """danbooru_tags.csv → {英語タグ名: DanbooruTag}"""
    path = path or DATA_DIR / "danbooru_tags.csv"
    result: dict[str, DanbooruTag] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tag = row["tag"]
            result[tag] = DanbooruTag(
                tag=tag,
                category=row.get("category", ""),
                count=int(row.get("count", 0)),
                genre=row.get("genre", "").strip(),
                ja=row.get("ja", "").strip(),
                memo=row.get("memo", ""),
            )
    logger.info("danbooru_tags.csv: %d 件", len(result))
    return result


def load_genres(path: Path | None = None) -> dict[str, GenreEntry]:
    """genre.csv → {key: GenreEntry}"""
    path = path or DATA_DIR / "genre.csv"
    result: dict[str, GenreEntry] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = row["key"]
            result[key] = GenreEntry(
                key=key,
                count=int(row.get("count", 0)),
                ja=row.get("ja", "").strip(),
            )
    logger.info("genre.csv: %d 件", len(result))
    return result


def load_category_rules(path: Path | None = None) -> list[CategoryRule]:
    """tag_category_rules.csv → [CategoryRule] (priority 降順)"""
    path = path or DATA_DIR / "tag_category_rules.csv"
    rules: list[CategoryRule] = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rules.append(
                CategoryRule(
                    match_type=row["match_type"],
                    pattern=row["pattern"],
                    category=row["category"],
                    priority=int(row.get("priority", 0)),
                )
            )
    rules.sort(key=lambda r: r.priority, reverse=True)
    logger.info("tag_category_rules.csv: %d 件", len(rules))
    return rules


def match_category_rule(tag: str, rules: list[CategoryRule]) -> str | None:
    """タグ名にマッチする最高優先度のルールのカテゴリを返す。マッチなしなら None。"""
    for rule in rules:
        if rule.match_type == "contains" and rule.pattern in tag:
            return rule.category
        if rule.match_type == "prefix" and tag.startswith(rule.pattern):
            return rule.category
        if rule.match_type == "suffix" and tag.endswith(rule.pattern):
            return rule.category
    return None


def load_translation_cache(path: Path | None = None) -> dict[str, str]:
    """translation_cache.csv (ヘッダなし en,ja) → {英語タグ名: 日本語名}"""
    path = path or DATA_DIR / "translation_cache.csv"
    result: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",", 1)
            if len(parts) == 2:
                result[parts[0]] = parts[1]
    logger.info("translation_cache.csv: %d 件", len(result))
    return result


# ---------------------------------------------------------------------------
# tag_palette.json 読み込み
# ---------------------------------------------------------------------------


LAST_IMPORT_FILE = "last_import.txt"


def _last_import_path(image_dir: Path) -> Path:
    return image_dir.parent / LAST_IMPORT_FILE


def load_last_import(image_dir: Path) -> datetime | None:
    path = _last_import_path(image_dir)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return datetime.fromisoformat(text)
    except (ValueError, OSError):
        return None


def save_last_import(image_dir: Path, run_time: datetime) -> None:
    path = _last_import_path(image_dir)
    path.write_text(run_time.isoformat(), encoding="utf-8")


def load_tag_palettes(
    image_dir: Path,
    *,
    since: datetime | None = None,
    since_generated: datetime | None = None,
) -> tuple[list[TagPaletteEntry], list[AudioPaletteEntry], list[NovelPaletteEntry]]:
    """images ディレクトリから tag_palette.json を読み込む。

    Returns:
        (media_entries, audio_entries, novel_entries) のタプル。
    """
    cutoff = since.timestamp() if since else 0
    entries: list[TagPaletteEntry] = []
    audio_entries: list[AudioPaletteEntry] = []
    novel_entries: list[NovelPaletteEntry] = []

    scanned = 0
    skipped = 0
    for info_dir in sorted(image_dir.iterdir()):
        if not info_dir.is_dir() or not info_dir.name.endswith(".info"):
            continue

        scanned += 1
        if scanned % 5000 == 0:
            logger.info(
                "スキャン中... %d ディレクトリ (media: %d, audio: %d, novel: %d, スキップ: %d)",
                scanned, len(entries), len(audio_entries), len(novel_entries), skipped,
            )

        tp_path = info_dir / "tag_palette.json"
        if not tp_path.exists():
            continue

        if cutoff and tp_path.stat().st_mtime < cutoff:
            skipped += 1
            continue

        try:
            with open(tp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("読み込み失敗: %s -> %s", tp_path, e)
            continue

        # generated_at フィルタ
        if since_generated:
            gen_at = data.get("generated_at", "")
            if gen_at and gen_at < since_generated.isoformat():
                skipped += 1
                continue

        media_type = data.get("media_type", "")

        # ── 音声エントリ ──
        if media_type == "audio":
            asset_id = data.get("id", info_dir.name.replace(".info", ""))
            audio_entries.append(
                AudioPaletteEntry(
                    asset_id=asset_id,
                    file_path=data.get("file_path", ""),
                    file_name=data.get("file_name", ""),
                    file_extension=data.get("file_extension", ""),
                    audio_type=data.get("audio_type", "bgm"),
                    duration_ms=data.get("duration_ms"),
                    sample_rate=data.get("sample_rate"),
                    file_size=data.get("file_size"),
                    description=data.get("description"),
                    transcript=data.get("transcript"),
                    model_name=data.get("model_name", ""),
                    tags=data.get("tags", {}),
                    generated_at=data.get("generated_at", ""),
                )
            )
            continue

        # ── 小説エントリ ──
        if media_type == "novel":
            novel_id = data.get("id", info_dir.name.replace(".info", ""))
            raw_tags = data.get("tags", [])
            novel_entries.append(
                NovelPaletteEntry(
                    novel_id=novel_id,
                    title=data.get("title", ""),
                    author=data.get("author", ""),
                    url=data.get("url", ""),
                    tags=raw_tags if isinstance(raw_tags, list) else [],
                    is_sensitive=bool(data.get("is_sensitive", False)),
                    num_chunks=data.get("num_chunks", 0),
                    num_morphemes=data.get("num_morphemes", 0),
                    chunks=data.get("chunks", []),
                    generated_at=data.get("generated_at", ""),
                )
            )
            continue

        # ── メディアエントリ (画像/動画/HTML) ──
        image_id = data.get("image_id") or data.get(
            "id", info_dir.name.replace(".info", "")
        )

        # embedding.npy を読み込み
        tag_embedding: bytes | None = None
        emb_path = info_dir / "embedding.npy"
        if emb_path.exists():
            try:
                arr = np.load(emb_path)
                tag_embedding = arr.astype(np.float32).tobytes()
            except Exception as e:
                logger.warning("embedding.npy 読み込み失敗: %s -> %s", emb_path, e)

        # ccip_embedding.npy を読み込み
        ccip_embedding: bytes | None = None
        ccip_path = info_dir / "ccip_embedding.npy"
        if ccip_path.exists():
            try:
                arr = np.load(ccip_path)
                ccip_embedding = arr.astype(np.float32).tobytes()
            except Exception as e:
                logger.warning("ccip_embedding.npy 読み込み失敗: %s -> %s", ccip_path, e)

        # pose_embedding.npy を読み込み
        pose_embedding: bytes | None = None
        pose_path = info_dir / "pose_embedding.npy"
        if pose_path.exists():
            try:
                arr = np.load(pose_path)
                pose_embedding = arr.astype(np.float32).tobytes()
            except Exception as e:
                logger.warning("pose_embedding.npy 読み込み失敗: %s -> %s", pose_path, e)

        entries.append(
            TagPaletteEntry(
                image_id=image_id,
                image_name=data.get("image_name") or data.get("name", ""),
                thumbnail_name=data.get("thumbnail_name", ""),
                ext=data.get("ext", ""),
                model_name=data.get("model_name", ""),
                genre=data.get("genre"),
                is_sensitive=bool(data.get("is_sensitive", False)),
                ai_score=data.get("ai_score"),
                real_score=data.get("real_score"),
                monochrome_score=data.get("monochrome_score"),
                classify_scores=data.get("classify_scores"),
                completeness_scores=data.get("completeness_scores"),
                portrait_scores=data.get("portrait_scores"),
                tags=data.get("tags", {}),
                tags_ja=data.get("tags_ja", {}),
                generated_at=data.get("generated_at", ""),
                info_dir=info_dir,
                tag_embedding=tag_embedding,
                ccip_embedding=ccip_embedding,
                pose_embedding=pose_embedding,
            )
        )

    html_count = sum(1 for e in entries if e.ext.lower().strip(".") in ("html", "htm"))
    image_count = len(entries) - html_count
    logger.info(
        "スキャン完了: %d ディレクトリ (image: %d, html: %d, novel: %d, audio: %d, スキップ: %d)",
        scanned, image_count, html_count, len(novel_entries), len(audio_entries), skipped,
    )
    return entries, audio_entries, novel_entries


# ---------------------------------------------------------------------------
# SQLite 直接書き込み
# ---------------------------------------------------------------------------

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chunked(iterable, size: int):
    it = iter(iterable)
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            break
        yield chunk


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
                stats["media_updated"] += 1
        else:
            conn.execute(
                "INSERT INTO media (id, file_path, file_name, file_extension, thumbnail_path, "
                "is_sensitive, ai_score, real_score, monochrome_score, classify_scores, completeness_scores, "
                "portrait_scores, media_type, genre_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (media_id, file_path, entry.image_name, entry.ext, thumbnail_path,
                 entry.is_sensitive, entry.ai_score, entry.real_score,
                 entry.monochrome_score, classify_json, completeness_json, portrait_json,
                 media_type, entry.genre, now),
            )
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


def import_audio_entries(
    conn: sqlite3.Connection,
    entries: list[AudioPaletteEntry],
) -> dict[str, int]:
    """音声エントリを audio_assets テーブルに書き込む。"""
    now = _now_iso()
    stats = {"audio_created": 0, "audio_updated": 0}

    # 既存 audio_assets を file_path で一括取得
    existing_audio: set[str] = set()
    all_paths = [e.file_path for e in entries]
    for batch in _chunked(all_paths, BATCH_SIZE):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"SELECT file_path FROM audio_assets WHERE file_path IN ({placeholders})", batch
        ).fetchall()
        existing_audio.update(r[0] for r in rows)

    for i, entry in enumerate(entries):
        if entry.file_path in existing_audio:
            # UPDATE: audio_type, duration, sample_rate, description
            conn.execute(
                "UPDATE audio_assets SET audio_type = ?, duration_ms = ?, sample_rate = ?, "
                "description = ?, file_size = ? WHERE file_path = ?",
                (entry.audio_type.upper(), entry.duration_ms, entry.sample_rate,
                 entry.description, entry.file_size, entry.file_path),
            )
            stats["audio_updated"] += 1
        else:
            conn.execute(
                "INSERT INTO audio_assets (id, file_path, file_name, file_extension, "
                "audio_type, duration_ms, sample_rate, description, file_size, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.asset_id, entry.file_path, entry.file_name, entry.file_extension,
                 entry.audio_type.upper(), entry.duration_ms, entry.sample_rate,
                 entry.description, entry.file_size, now),
            )
            existing_audio.add(entry.file_path)
            stats["audio_created"] += 1

        if (i + 1) % 1000 == 0:
            conn.commit()
            logger.info("音声インポート: %d / %d 件", i + 1, len(entries))

    conn.commit()
    return stats


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


# ---------------------------------------------------------------------------
# ポストインポート: desc_text + desc_embedding 生成
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------


def main() -> None:
    from env_config import get_db_path as _get_db_path, get_image_dir

    parser = argparse.ArgumentParser(description="tag_palette.json → SQLite 直接インポート")
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=get_image_dir(),
        help="Eagle ライブラリの images ディレクトリ (env: EAGLE_IMAGE_DIR)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=_get_db_path(),
        help="SQLite DB パス (env: SQLITE_DB_PATH)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="読み込みのみ (DB 書き込みしない)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="全件再インポート (前回実行時刻を無視)",
    )
    parser.add_argument(
        "--since-generated",
        type=str,
        default=None,
        help="generated_at がこの日時以降のエントリのみ対象 (例: 2026-03-23T15:40:00)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    if not args.image_dir:
        parser.error("--image-dir または環境変数 EAGLE_IMAGE_DIR を指定してください")
    if not args.image_dir.is_dir():
        logger.error("ディレクトリが見つかりません: %s", args.image_dir)
        sys.exit(1)
    if not args.db_path:
        parser.error("--db-path または環境変数 SQLITE_DB_PATH を指定してください")
    if not args.db_path.exists():
        logger.error("DB が見つかりません: %s", args.db_path)
        sys.exit(1)

    # 今回の実行時刻を記録 (探索前に取得)
    run_time = datetime.now(timezone.utc)

    # 前回実行時刻
    if args.force:
        since = None
        logger.info("--force: 全件を対象にします")
    else:
        since = load_last_import(args.image_dir)
        if since:
            logger.info("前回インポート: %s", since.isoformat())
        else:
            logger.info("初回インポート: 全件を対象にします")

    # CSV マスタ読み込み
    category_csv = load_categories()
    danbooru = load_danbooru_tags()
    genre_csv = load_genres()
    trans_cache = load_translation_cache()
    category_rules = load_category_rules()

    # --since-generated が指定された場合は since を無視
    since_generated = None
    if args.since_generated:
        since_generated = datetime.fromisoformat(args.since_generated)
        since = None
        logger.info("--since-generated: %s 以降に生成されたエントリのみ対象", since_generated.isoformat())

    # tag_palette.json 読み込み
    entries, audio_entries, novel_entries = load_tag_palettes(
        args.image_dir, since=since, since_generated=since_generated,
    )
    if not entries and not audio_entries and not novel_entries:
        logger.info("対象の tag_palette.json がありません。")
        save_last_import(args.image_dir, run_time)
        return

    if args.dry_run:
        logger.info(
            "dry-run: media %d 件, audio %d 件, novel %d 件。書き込みスキップ。",
            len(entries), len(audio_entries), len(novel_entries),
        )
        for e in entries[:3]:
            if e.tags:
                sample_tag = next(iter(e.tags))
                sample_ja = e.tags_ja.get(sample_tag, sample_tag)
                logger.info(
                    "  [media] %s: %d tags, sample: %s → %s",
                    e.image_name,
                    len(e.tags),
                    sample_tag,
                    sample_ja,
                )
        for a in audio_entries[:3]:
            logger.info(
                "  [audio] %s: %s, %dms",
                a.file_name,
                a.audio_type,
                a.duration_ms or 0,
            )
        for n in novel_entries[:3]:
            logger.info(
                "  [novel] %s: %s, %d chunks",
                n.title,
                n.author,
                n.num_chunks,
            )
        return

    # 全エントリのタグ名を収集
    all_entry_tags: set[str] = set()
    for e in entries:
        all_entry_tags.update(e.tags.keys())

    # SQLite に直接書き込み
    conn = sqlite3.connect(str(args.db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        logger.info("DB: %s", args.db_path)

        # 1. マスタデータ同期
        if entries:
            sync_master_data(
                conn, danbooru, genre_csv, category_csv, trans_cache,
                all_entry_tags, category_rules,
            )

        # 2. メディアエントリインポート
        if entries:
            stats = import_entries(conn, entries)
            logger.info("メディアインポート完了:")
            for key, val in stats.items():
                if val:
                    logger.info("  %s: %d", key, val)

        # 3. 音声エントリインポート
        if audio_entries:
            audio_stats = import_audio_entries(conn, audio_entries)
            logger.info("音声インポート完了:")
            for key, val in audio_stats.items():
                if val:
                    logger.info("  %s: %d", key, val)

        # 4. 小説エントリインポート
        if novel_entries:
            novel_stats = import_novel_entries(conn, novel_entries)
            logger.info("小説インポート完了:")
            for key, val in novel_stats.items():
                if val:
                    logger.info("  %s: %d", key, val)

        # 5. desc_text + desc_embedding 補完（オプション）
        try:
            post_import_desc(conn)
        except ImportError as e:
            logger.info("desc 補完スキップ（モジュール未インストール: %s）", e)

    finally:
        conn.close()

    save_last_import(args.image_dir, run_time)


if __name__ == "__main__":
    main()
