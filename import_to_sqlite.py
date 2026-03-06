"""Eagle ライブラリの tag_palette.json を SQLite にインポートする。

images ディレクトリ内の各 *.info/tag_palette.json を読み取り、
CSV マスタデータ (danbooru_tags / genre / translation_cache) で補完したうえで
tags / media / media_tags / genres / categories / tag_genres テーブルへ書き込む。

Usage:
    uv run python import_to_sqlite.py \
        --image-dir /Volumes/Shared/eagle.library/images \
        --db /path/to/local.db
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
from pathlib import Path

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

VIDEO_EXTENSIONS = {"mp4", "webm", "avi", "mov", "mkv", "flv", "wmv", "mpg", "mpeg", "gif"}


def _media_type(ext: str) -> str:
    """拡張子から media_type を判定する。"""
    return "VIDEO" if ext.lower().strip(".") in VIDEO_EXTENSIONS else "IMAGE"

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


def load_translation_cache(path: Path | None = None) -> dict[str, str]:
    """translation_cache.csv (ヘッダなし en,ja) → {英語タグ名: 日本語名}

    tags テーブルの id / name マスタとして使用する。
    """
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


def load_tag_palettes(image_dir: Path) -> list[TagPaletteEntry]:
    """images ディレクトリから全 tag_palette.json を読み込む。"""
    entries: list[TagPaletteEntry] = []

    for info_dir in sorted(image_dir.iterdir()):
        if not info_dir.is_dir() or not info_dir.name.endswith(".info"):
            continue

        tp_path = info_dir / "tag_palette.json"
        if not tp_path.exists():
            continue

        try:
            with open(tp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("読み込み失敗: %s -> %s", tp_path, e)
            continue

        image_id = data.get("image_id") or data.get("id", info_dir.name.replace(".info", ""))

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
                tags=data.get("tags", {}),
                tags_ja=data.get("tags_ja", {}),
                generated_at=data.get("generated_at", ""),
                info_dir=info_dir,
                tag_embedding=tag_embedding,
                ccip_embedding=ccip_embedding,
            )
        )

    logger.info("tag_palette.json: %d 件", len(entries))
    return entries



# ---------------------------------------------------------------------------
# SQLite 書き込み
# ---------------------------------------------------------------------------


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def import_to_sqlite(
    db_path: Path,
    entries: list[TagPaletteEntry],
    danbooru: dict[str, DanbooruTag],
    genres: dict[str, GenreEntry],
    category_csv: dict[str, CategoryEntry],
    trans_cache: dict[str, str],
) -> None:
    """tag_palette エントリを SQLite に書き込む。"""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        _do_import(conn, entries, danbooru, genres, category_csv, trans_cache)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_categories(
    conn: sqlite3.Connection,
    category_csv: dict[str, CategoryEntry],
    now: str,
) -> dict[str, str]:
    """categories テーブルを category.csv で同期。{csv_id: db_id} を返す。"""
    # 既存: name → id (DB上の name は日本語名)
    existing_by_name: dict[str, str] = {}
    existing_ids: set[str] = set()
    for row in conn.execute("SELECT id, name FROM categories"):
        existing_by_name[row[1]] = row[0]
        existing_ids.add(row[0])

    csv_id_to_db_id: dict[str, str] = {}

    for cat_id, entry in category_csv.items():
        if cat_id in existing_ids:
            # id が既に存在 → そのまま使う
            csv_id_to_db_id[cat_id] = cat_id
        elif entry.name in existing_by_name:
            # 日本語名で既存マッチ → 既存 id を使う
            csv_id_to_db_id[cat_id] = existing_by_name[entry.name]
        else:
            # 新規追加 (id = CSV の id をそのまま使用)
            conn.execute(
                "INSERT INTO categories (id, name, created_at) VALUES (?, ?, ?)",
                (cat_id, entry.name, now),
            )
            csv_id_to_db_id[cat_id] = cat_id
            logger.info("カテゴリ追加: %s (%s)", cat_id, entry.name)

    return csv_id_to_db_id


def _ensure_genres(
    conn: sqlite3.Connection,
    genre_csv: dict[str, GenreEntry],
    now: str,
) -> None:
    """genres テーブルを確認し、genre.csv の全エントリを投入。{key: id} を返す。"""
    existing_ids: set[str] = set()
    for row in conn.execute("SELECT id FROM genres"):
        existing_ids.add(row[0])

    for key, entry in genre_csv.items():
        if key not in existing_ids:
            display_name = entry.ja or key
            conn.execute(
                "INSERT INTO genres (id, name, created_at) VALUES (?, ?, ?)",
                (key, display_name, now),
            )
            existing_ids.add(key)
            logger.info("ジャンル追加: %s (%s)", key, display_name)


def _do_import(
    conn: sqlite3.Connection,
    entries: list[TagPaletteEntry],
    danbooru: dict[str, DanbooruTag],
    genre_csv: dict[str, GenreEntry],
    category_csv: dict[str, CategoryEntry],
    trans_cache: dict[str, str],
) -> None:
    now = _now_iso()

    # ── 0. マスタテーブル準備 ─────────────────────────────────
    csv_id_to_db_id = _ensure_categories(conn, category_csv, now)
    _ensure_genres(conn, genre_csv, now)

    # danbooru category code → DB category id
    cat_code_to_id: dict[str, str] = {}
    for code, csv_name in DANBOORU_CATEGORY_MAP.items():
        if csv_name in csv_id_to_db_id:
            cat_code_to_id[code] = csv_id_to_db_id[csv_name]

    # ── 1. 既存キャッシュ読み込み ────────────────────────────
    existing_tag_ids: set[str] = set()
    for row in conn.execute("SELECT id FROM tags"):
        existing_tag_ids.add(row[0])

    existing_tag_genres: set[tuple[str, str]] = set()
    for row in conn.execute("SELECT tag_id, genre_id FROM tag_genres"):
        existing_tag_genres.add((row[0], row[1]))

    stats = {
        "tags_created": 0,
        "tags_updated": 0,
        "tag_genres_created": 0,
        "media_created": 0,
        "media_tags_created": 0,
    }

    # ── 1a. danbooru_tags からタグマスタ投入 (メイン) ─────────
    #    id=英語タグ名, name=日本語名, category_id, tag_genres
    danbooru_inserted = 0
    for tag_en, db_tag in danbooru.items():
        if tag_en in existing_tag_ids:
            continue
        category_id = None
        if db_tag.category in cat_code_to_id:
            category_id = cat_code_to_id[db_tag.category]
        tag_ja = db_tag.ja or tag_en
        sensitive = int(is_sensitive(tag_en))
        conn.execute(
            """
            INSERT INTO tags (id, name, category_id, is_favorite, is_sensitive, disable, created_at)
            VALUES (?, ?, ?, 0, ?, 0, ?)
            """,
            (tag_en, tag_ja, category_id, sensitive, now),
        )
        existing_tag_ids.add(tag_en)
        danbooru_inserted += 1
        # tag_genres リレーション
        if db_tag.genre and db_tag.genre in genre_csv:
            tg_key = (tag_en, db_tag.genre)
            if tg_key not in existing_tag_genres:
                conn.execute(
                    "INSERT INTO tag_genres (id, tag_id, genre_id, created_at) VALUES (?, ?, ?, ?)",
                    (_new_uuid(), tag_en, db_tag.genre, now),
                )
                existing_tag_genres.add(tg_key)
                stats["tag_genres_created"] += 1
    if danbooru_inserted:
        logger.info("danbooru_tags からタグ投入: %d 件", danbooru_inserted)

    # ── 1b. translation_cache で補完 ─────────────────────────
    #    danbooru にないタグを追加 + 日本語名を上書き更新
    tc_inserted = 0
    tc_updated = 0
    for tag_en, tag_ja in trans_cache.items():
        if tag_en not in existing_tag_ids:
            sensitive = int(is_sensitive(tag_en))
            conn.execute(
                """
                INSERT INTO tags (id, name, category_id, is_favorite, is_sensitive, disable, created_at)
                VALUES (?, ?, NULL, 0, ?, 0, ?)
                """,
                (tag_en, tag_ja, sensitive, now),
            )
            existing_tag_ids.add(tag_en)
            tc_inserted += 1
        else:
            # danbooru の ja が空の場合、translation_cache で上書き
            conn.execute(
                "UPDATE tags SET name = ? WHERE id = ? AND (name IS NULL OR name = '' OR name = ?)",
                (tag_ja, tag_en, tag_en),
            )
            tc_updated += 1
    if tc_inserted or tc_updated:
        logger.info("translation_cache: 追加 %d 件, 日本語名更新 %d 件", tc_inserted, tc_updated)

    # ── 2. 既存 media (file_path → id) キャッシュ ─────────────
    media_path_to_id: dict[str, str] = {}
    for row in conn.execute("SELECT id, file_path FROM media"):
        media_path_to_id[row[1]] = row[0]

    for entry in entries:
        # ── media ─────────────────────────────────────────────
        file_path = f"images/{entry.image_id}.info/{entry.image_name}"
        thumbnail_path = f"images/{entry.image_id}.info/{entry.thumbnail_name}"

        if file_path in media_path_to_id:
            media_id = media_path_to_id[file_path]
            # 既存レコードの embedding が NULL なら更新
            if entry.tag_embedding:
                conn.execute(
                    "UPDATE media SET tag_embedding = ? WHERE id = ? AND tag_embedding IS NULL",
                    (entry.tag_embedding, media_id),
                )
            if entry.ccip_embedding:
                conn.execute(
                    "UPDATE media SET ccip_embedding = ? WHERE id = ? AND ccip_embedding IS NULL",
                    (entry.ccip_embedding, media_id),
                )
        else:
            media_id = entry.image_id
            genre_id = entry.genre if entry.genre and entry.genre in genre_csv else None
            media_type = _media_type(entry.ext)
            conn.execute(
                """
                INSERT INTO media (id, file_path, file_name, file_extension, thumbnail_path,
                                   tag_embedding, ccip_embedding, is_favorite, is_sensitive, view_count,
                                   media_type, genre_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?, ?)
                """,
                (media_id, file_path, entry.image_name, entry.ext, thumbnail_path,
                 entry.tag_embedding, entry.ccip_embedding, int(entry.is_sensitive), media_type, genre_id, now),
            )
            media_path_to_id[file_path] = media_id
            stats["media_created"] += 1

        # ── 既存 media_tags 削除 (同モデル再インポート) ────────
        conn.execute(
            "DELETE FROM media_tags WHERE media_id = ? AND model_name = ?",
            (media_id, entry.model_name),
        )

        # ── tags / media_tags ─────────────────────────────────
        for tag_en, confidence in entry.tags.items():
            tag_ja = entry.tags_ja.get(tag_en, tag_en)
            db_tag = danbooru.get(tag_en)

            # tag_id = 英語タグ名
            tag_id = tag_en

            if tag_id not in existing_tag_ids:
                # danbooru / translation_cache に無かったタグ → 新規追加
                category_id = None
                if db_tag and db_tag.category in cat_code_to_id:
                    category_id = cat_code_to_id[db_tag.category]
                sensitive = int(is_sensitive(tag_id))
                conn.execute(
                    """
                    INSERT INTO tags (id, name, category_id, is_favorite, is_sensitive, disable, created_at)
                    VALUES (?, ?, ?, 0, ?, 0, ?)
                    """,
                    (tag_id, tag_ja, category_id, sensitive, now),
                )
                existing_tag_ids.add(tag_id)
                stats["tags_created"] += 1
            else:
                # category_id が未設定なら UPDATE
                category_id = None
                if db_tag and db_tag.category in cat_code_to_id:
                    category_id = cat_code_to_id[db_tag.category]
                if category_id:
                    conn.execute(
                        "UPDATE tags SET category_id = ? WHERE id = ? AND category_id IS NULL",
                        (category_id, tag_id),
                    )
                    stats["tags_updated"] += 1

            # tag_genres リレーション
            if db_tag and db_tag.genre and db_tag.genre in genre_csv:
                genre_id = db_tag.genre
                if (tag_id, genre_id) not in existing_tag_genres:
                    tg_id = _new_uuid()
                    conn.execute(
                        "INSERT INTO tag_genres (id, tag_id, genre_id, created_at) VALUES (?, ?, ?, ?)",
                        (tg_id, tag_id, genre_id, now),
                    )
                    existing_tag_genres.add((tag_id, genre_id))
                    stats["tag_genres_created"] += 1

            # media_tag INSERT
            mt_id = _new_uuid()
            conn.execute(
                """
                INSERT INTO media_tags (id, media_id, tag_id, confidence, model_name, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (mt_id, media_id, tag_id, confidence, entry.model_name, now),
            )
            stats["media_tags_created"] += 1

    logger.info("インポート完了:")
    for k, v in stats.items():
        if v:
            logger.info("  %s: %d", k, v)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------


def main() -> None:
    from env_config import get_db_path, get_image_dir

    parser = argparse.ArgumentParser(description="tag_palette.json → SQLite インポート")
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=get_image_dir(),
        help="Eagle ライブラリの images ディレクトリ (env: EAGLE_IMAGE_DIR)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=get_db_path(),
        help="SQLite データベースファイルパス (env: SQLITE_DB_PATH)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="読み込みのみ (書き込みしない)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    if not args.image_dir:
        parser.error("--image-dir または環境変数 EAGLE_IMAGE_DIR を指定してください")
    if not args.db:
        parser.error("--db または環境変数 SQLITE_DB_PATH を指定してください")
    if not args.image_dir.is_dir():
        logger.error("ディレクトリが見つかりません: %s", args.image_dir)
        sys.exit(1)

    if not args.db.exists():
        logger.error("DB ファイルが見つかりません: %s", args.db)
        sys.exit(1)

    # CSV マスタ読み込み
    category_csv = load_categories()
    danbooru = load_danbooru_tags()
    genre_csv = load_genres()
    trans_cache = load_translation_cache()

    # tag_palette.json 読み込み
    entries = load_tag_palettes(args.image_dir)
    if not entries:
        logger.info("対象の tag_palette.json がありません。")
        return

    if args.dry_run:
        logger.info("dry-run: %d 件読み込み済み。書き込みスキップ。", len(entries))
        for e in entries[:3]:
            sample_tag = next(iter(e.tags))
            sample_ja = e.tags_ja.get(sample_tag, sample_tag)
            logger.info("  %s: %d tags, sample: %s → %s", e.image_name, len(e.tags), sample_tag, sample_ja)
        return

    import_to_sqlite(args.db, entries, danbooru, genre_csv, category_csv, trans_cache)


if __name__ == "__main__":
    main()
