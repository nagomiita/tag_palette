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
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

import sqlite3

import numpy as np

from tag_palette import is_sensitive

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
    """tag_palette.json 1件分。"""

    image_id: str
    image_name: str
    thumbnail_name: str
    ext: str
    model_name: str
    genre: str | None
    is_sensitive: bool
    ai_score: float | None
    tags: dict[str, float]  # {英語タグ: confidence}
    tags_ja: dict[str, str]  # {英語タグ: 日本語名}
    generated_at: str
    info_dir: Path
    tag_embedding: bytes | None  # embedding.npy から読み込んだ生バイト
    ccip_embedding: bytes | None  # ccip_embedding.npy から読み込んだ生バイト


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
    image_dir: Path, *, since: datetime | None = None
) -> list[TagPaletteEntry]:
    """images ディレクトリから tag_palette.json を読み込む。"""
    cutoff = since.timestamp() if since else 0
    entries: list[TagPaletteEntry] = []

    scanned = 0
    skipped = 0
    for info_dir in sorted(image_dir.iterdir()):
        if not info_dir.is_dir() or not info_dir.name.endswith(".info"):
            continue

        scanned += 1
        if scanned % 5000 == 0:
            logger.info("スキャン中... %d ディレクトリ (読み込み: %d, スキップ: %d)", scanned, len(entries), skipped)

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
                tags=data.get("tags", {}),
                tags_ja=data.get("tags_ja", {}),
                generated_at=data.get("generated_at", ""),
                info_dir=info_dir,
                tag_embedding=tag_embedding,
                ccip_embedding=ccip_embedding,
            )
        )

    logger.info("スキャン完了: %d ディレクトリ (読み込み: %d, スキップ: %d)", scanned, len(entries), skipped)
    return entries


# ---------------------------------------------------------------------------
# SQLite 直接書き込み
# ---------------------------------------------------------------------------

_VIDEO_EXTENSIONS = {
    "mp4", "webm", "mkv", "avi", "mov", "wmv", "flv", "m4v", "mpg", "mpeg",
}
_COMIC_TAGS = {"comic", "greyscale", "monochrome", "speech_bubble"}


def _detect_media_type(ext: str, tags: dict[str, float] | None = None) -> str:
    if ext.lower().strip(".") in _VIDEO_EXTENSIONS:
        return "VIDEO"
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
        sensitive = is_sensitive(tag_en)
        conn.execute(
            "INSERT INTO tags (id, name, category_id, is_sensitive, is_favorite, disable, created_at) VALUES (?, ?, ?, ?, 0, 0, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, category_id = excluded.category_id, is_sensitive = excluded.is_sensitive",
            (tag_en, tag_ja, category_id, sensitive, now),
        )
        tag_count += 1
        seen_tag_ids.add(tag_en)

        if db_tag.genre and db_tag.genre in genres:
            tag_genre_data.append((f"{tag_en}__{db_tag.genre}", tag_en, db_tag.genre))

    # 3b. translation_cache（danbooru にないもの）
    for tag_en, tag_ja in trans_cache.items():
        if tag_en not in seen_tag_ids:
            sensitive = is_sensitive(tag_en)
            conn.execute(
                "INSERT INTO tags (id, name, is_sensitive, is_favorite, disable, created_at) VALUES (?, ?, ?, 0, 0, ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name, is_sensitive = excluded.is_sensitive",
                (tag_en, _resolve_name(tag_en, tag_ja), sensitive, now),
            )
            tag_count += 1
            seen_tag_ids.add(tag_en)

    # 3c. entry にあるが danbooru/translation_cache にないタグ
    for tag_en in entry_tags:
        if tag_en not in seen_tag_ids:
            conn.execute(
                "INSERT INTO tags (id, name, is_sensitive, is_favorite, disable, created_at) VALUES (?, ?, ?, 0, 0, ?) "
                "ON CONFLICT(id) DO NOTHING",
                (tag_en, _resolve_name(tag_en, tag_en), is_sensitive(tag_en), now),
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
        if media_id in existing_media:
            if entry.ai_score is not None:
                conn.execute(
                    "UPDATE media SET ai_score = ? WHERE id = ? AND ai_score IS NULL",
                    (entry.ai_score, media_id),
                )
                stats["media_updated"] += 1
        else:
            conn.execute(
                "INSERT INTO media (id, file_path, file_name, file_extension, thumbnail_path, "
                "is_sensitive, ai_score, media_type, genre_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (media_id, file_path, entry.image_name, entry.ext, thumbnail_path,
                 entry.is_sensitive, entry.ai_score, media_type, entry.genre, now),
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
        if entry.tag_embedding or entry.ccip_embedding:
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
            else:
                conn.execute(
                    "INSERT INTO media_embeddings (media_id, tag_embedding, ccip_embedding) VALUES (?, ?, ?)",
                    (media_id, entry.tag_embedding, entry.ccip_embedding),
                )
                existing_emb.add(media_id)

        if (i + 1) % 1000 == 0:
            conn.commit()
            logger.info("エントリインポート: %d / %d 件", i + 1, len(entries))

    conn.commit()
    return stats


# ---------------------------------------------------------------------------
# ポストインポート: desc_text + desc_embedding 生成
# ---------------------------------------------------------------------------

DESC_MODEL = "tag-based-v1"
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"

# DB の category_id → compose_description が期待するカテゴリ名
_CATEGORY_MAP: dict[str | None, str] = {
    "character": "characters",
    "meta": "meta",
    "appearance": "appearance",
    "costume": "costume",
    "pose": "pose",
    "emotion": "emotion",
    "composition": "composition",
    "background": "situation",
    "copyright": "meta",
    "general": "general",
    None: "general",
}


def _backfill_desc_text(conn: sqlite3.Connection) -> int:
    """desc_text が NULL のメディアにタグベース説明文を生成して埋める。"""
    from infer_csv_descriptions import compose_description

    media_ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM media WHERE desc_text IS NULL OR desc_text = ''"
        ).fetchall()
    ]
    if not media_ids:
        return 0

    # タグを一括取得
    placeholders = ",".join("?" for _ in media_ids)
    tag_rows = conn.execute(
        f"""
        SELECT mt.media_id, t.name, t.category_id
        FROM media_tags mt
        JOIN tags t ON t.id = mt.tag_id
        WHERE mt.media_id IN ({placeholders})
        """,
        media_ids,
    ).fetchall()

    tags_by_media: dict[str, dict[str, list[str]]] = {mid: {} for mid in media_ids}
    for media_id, tag_name, category_id in tag_rows:
        if not tag_name:
            continue
        cat = _CATEGORY_MAP.get(category_id, "general")
        tags_by_media[media_id].setdefault(cat, []).append(tag_name)

    updated = 0
    for media_id in media_ids:
        raw_tags = tags_by_media.get(media_id, {})
        if not any(raw_tags.values()):
            continue
        description, _confidence = compose_description(raw_tags)
        conn.execute(
            "UPDATE media SET desc_text = ?, desc_model = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
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

    # tag_palette.json 読み込み
    entries = load_tag_palettes(args.image_dir, since=since)
    if not entries:
        logger.info("対象の tag_palette.json がありません。")
        save_last_import(args.image_dir, run_time)
        return

    if args.dry_run:
        logger.info("dry-run: %d 件読み込み済み。書き込みスキップ。", len(entries))
        for e in entries[:3]:
            if e.tags:
                sample_tag = next(iter(e.tags))
                sample_ja = e.tags_ja.get(sample_tag, sample_tag)
                logger.info(
                    "  %s: %d tags, sample: %s → %s",
                    e.image_name,
                    len(e.tags),
                    sample_tag,
                    sample_ja,
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
        sync_master_data(
            conn, danbooru, genre_csv, category_csv, trans_cache,
            all_entry_tags, category_rules,
        )

        # 2. エントリインポート
        stats = import_entries(conn, entries)

        logger.info("インポート完了:")
        for key, val in stats.items():
            if val:
                logger.info("  %s: %d", key, val)

        # 3. desc_text + desc_embedding 補完（オプション）
        try:
            post_import_desc(conn)
        except ImportError as e:
            logger.info("desc 補完スキップ（モジュール未インストール: %s）", e)

    finally:
        conn.close()

    save_last_import(args.image_dir, run_time)


if __name__ == "__main__":
    main()
