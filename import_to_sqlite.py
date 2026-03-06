"""Eagle ライブラリの tag_palette.json を Eagle API 経由でインポートする。

images ディレクトリ内の各 *.info/tag_palette.json を読み取り、
CSV マスタデータ (danbooru_tags / genre / translation_cache) で補完したうえで
Eagle API (merge + 専用インポートエンドポイント) に送信する。

Usage:
    uv run python import_to_sqlite.py \
        --image-dir /Volumes/Shared/eagle.library/images
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

import httpx
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

BATCH_SIZE_TAGS = 500
BATCH_SIZE_TAG_GENRES = 500
BATCH_SIZE_ENTRIES = 200


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
# API クライアント
# ---------------------------------------------------------------------------


def _chunked(iterable, size: int):
    """イテラブルを size 件ずつのチャンクに分割する。"""
    it = iter(iterable)
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            break
        yield chunk


class EagleApiClient:
    """Eagle バックエンド API クライアント。"""

    def __init__(self, base_url: str):
        self.client = httpx.Client(base_url=base_url, timeout=120)

    def close(self) -> None:
        self.client.close()

    def merge(self, model: str, data: list[dict], *, mode: str = "optimize") -> dict:
        """POST /orm/merge/{model}"""
        resp = self.client.post(
            f"/orm/merge/{model}",
            json={
                "data": data,
                "caller": "tag-palette/import",
                "mode": mode,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def import_entries(self, model_name: str, entries: list[dict]) -> dict:
        """POST /tenant/tag-palette-import/"""
        resp = self.client.post(
            "/tenant/tag-palette-import/",
            json={
                "model_name": model_name,
                "entries": entries,
            },
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# マスタデータ同期（merge API 経由）
# ---------------------------------------------------------------------------


def sync_master_data(
    api: EagleApiClient,
    danbooru: dict[str, DanbooruTag],
    genres: dict[str, GenreEntry],
    categories: dict[str, CategoryEntry],
    trans_cache: dict[str, str],
    entry_tags: set[str],
) -> None:
    """カテゴリ・ジャンル・タグ・タグジャンルを merge API で同期する。"""

    # ── 1. カテゴリ ──────────────────────────────────────────
    cat_data = [{"id": c.id, "name": c.name} for c in categories.values()]
    if cat_data:
        api.merge("category", cat_data)
        logger.info("カテゴリ同期: %d 件", len(cat_data))

    # カテゴリコード → ID マッピング
    cat_code_to_id: dict[str, str] = {}
    for code, csv_name in DANBOORU_CATEGORY_MAP.items():
        if csv_name in categories:
            cat_code_to_id[code] = categories[csv_name].id

    # ── 2. ジャンル ──────────────────────────────────────────
    genre_data = [
        {"id": g.key, "name": g.ja or g.key}
        for g in genres.values()
    ]
    if genre_data:
        api.merge("genre", genre_data)
        logger.info("ジャンル同期: %d 件", len(genre_data))

    # ── 3. タグ（danbooru + translation_cache + entry 未登録分）────
    tag_data: list[dict] = []
    tag_genre_data: list[dict] = []
    seen_tag_ids: set[str] = set()

    # 3a. danbooru_tags
    for tag_en, db_tag in danbooru.items():
        category_id = cat_code_to_id.get(db_tag.category)
        tag_ja = db_tag.ja or tag_en
        sensitive = is_sensitive(tag_en)
        tag_data.append({
            "id": tag_en,
            "name": tag_ja,
            "categoryId": category_id,
            "isSensitive": sensitive,
        })
        seen_tag_ids.add(tag_en)

        # tag_genres（決定論的 ID で冪等性を保証）
        if db_tag.genre and db_tag.genre in genres:
            tag_genre_data.append({
                "id": f"{tag_en}__{db_tag.genre}",
                "tagId": tag_en,
                "genreId": db_tag.genre,
            })

    # 3b. translation_cache（danbooru にないもの）
    for tag_en, tag_ja in trans_cache.items():
        if tag_en not in seen_tag_ids:
            sensitive = is_sensitive(tag_en)
            tag_data.append({
                "id": tag_en,
                "name": tag_ja,
                "isSensitive": sensitive,
            })
            seen_tag_ids.add(tag_en)

    # 3c. entry にあるが danbooru/translation_cache にないタグ
    for tag_en in entry_tags:
        if tag_en not in seen_tag_ids:
            tag_data.append({
                "id": tag_en,
                "name": tag_en,
                "isSensitive": is_sensitive(tag_en),
            })
            seen_tag_ids.add(tag_en)

    # バッチ送信
    for i, batch in enumerate(_chunked(tag_data, BATCH_SIZE_TAGS)):
        api.merge("tag", batch)
        if (i + 1) % 10 == 0 or (i + 1) * BATCH_SIZE_TAGS >= len(tag_data):
            logger.info("タグ同期: %d / %d 件", min((i + 1) * BATCH_SIZE_TAGS, len(tag_data)), len(tag_data))

    # ── 4. タグジャンル ──────────────────────────────────────
    for batch in _chunked(tag_genre_data, BATCH_SIZE_TAG_GENRES):
        api.merge("tag_genre", batch)
    if tag_genre_data:
        logger.info("タグジャンル同期: %d 件", len(tag_genre_data))


# ---------------------------------------------------------------------------
# エントリインポート（専用 API 経由）
# ---------------------------------------------------------------------------


def import_entries_via_api(
    api: EagleApiClient,
    entries: list[TagPaletteEntry],
) -> None:
    """tag_palette エントリを専用 API でバッチインポートする。"""
    total_created = 0
    total_updated = 0
    total_media_tags = 0
    total_auto_tags = 0

    for i, batch in enumerate(_chunked(entries, BATCH_SIZE_ENTRIES)):
        api_entries = []
        for entry in batch:
            api_entry: dict = {
                "image_id": entry.image_id,
                "image_name": entry.image_name,
                "thumbnail_name": entry.thumbnail_name,
                "ext": entry.ext,
                "genre": entry.genre,
                "is_sensitive": entry.is_sensitive,
                "ai_score": entry.ai_score,
                "tags": entry.tags,
            }
            if entry.tag_embedding:
                api_entry["tag_embedding"] = base64.b64encode(entry.tag_embedding).decode()
            if entry.ccip_embedding:
                api_entry["ccip_embedding"] = base64.b64encode(entry.ccip_embedding).decode()
            api_entries.append(api_entry)

        # model_name はバッチ内で統一（通常は同一モデル）
        model_name = batch[0].model_name
        result = api.import_entries(model_name, api_entries)

        total_created += result.get("media_created", 0)
        total_updated += result.get("media_updated", 0)
        total_media_tags += result.get("media_tags_created", 0)
        total_auto_tags += result.get("tags_auto_created", 0)

        processed = min((i + 1) * BATCH_SIZE_ENTRIES, len(entries))
        logger.info("エントリインポート: %d / %d 件", processed, len(entries))

    logger.info("インポート完了:")
    if total_created:
        logger.info("  media_created: %d", total_created)
    if total_updated:
        logger.info("  media_updated: %d", total_updated)
    if total_media_tags:
        logger.info("  media_tags_created: %d", total_media_tags)
    if total_auto_tags:
        logger.info("  tags_auto_created: %d", total_auto_tags)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------


def main() -> None:
    from env_config import get_api_url, get_image_dir

    parser = argparse.ArgumentParser(description="tag_palette.json → Eagle API インポート")
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=get_image_dir(),
        help="Eagle ライブラリの images ディレクトリ (env: EAGLE_IMAGE_DIR)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=get_api_url(),
        help="Eagle API の URL (env: EAGLE_API_URL, default: http://localhost:8000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="読み込みのみ (API 送信しない)",
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

    # 全エントリのタグ名を収集（マスタデータ同期用）
    all_entry_tags: set[str] = set()
    for e in entries:
        all_entry_tags.update(e.tags.keys())

    # API 経由でインポート
    api = EagleApiClient(args.api_url)
    try:
        logger.info("Eagle API: %s", args.api_url)

        # 1. マスタデータ同期
        sync_master_data(api, danbooru, genre_csv, category_csv, trans_cache, all_entry_tags)

        # 2. エントリインポート
        import_entries_via_api(api, entries)
    finally:
        api.close()

    save_last_import(args.image_dir, run_time)


if __name__ == "__main__":
    main()
