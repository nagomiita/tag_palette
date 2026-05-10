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
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from tag_palette.importer.audio_importer import import_audio_entries
from tag_palette.importer.csv_loader import (
    load_categories,
    load_category_rules,
    load_danbooru_tags,
    load_genres,
    load_translation_cache,
)
from tag_palette.importer.desc_backfill import post_import_desc
from tag_palette.importer.media_importer import import_entries, sync_master_data, sync_tag_embeddings
from tag_palette.importer.novel_importer import import_novel_entries
from tag_palette.importer.reader import (
    load_last_import,
    load_tag_palettes,
    save_last_import,
)

logger = logging.getLogger(__name__)


def main() -> None:
    from tag_palette.shared.env_config import get_db_path as _get_db_path, get_image_dir

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
    run_time = datetime.now()

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
                    e.image_name, len(e.tags), sample_tag, sample_ja,
                )
        for a in audio_entries[:3]:
            logger.info(
                "  [audio] %s: %s, %dms",
                a.file_name, a.audio_type, a.duration_ms or 0,
            )
        for n in novel_entries[:3]:
            logger.info(
                "  [novel] %s: %s, %d chunks",
                n.title, n.author, n.num_chunks,
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

        # 2. タグ埋め込み同期
        if entries:
            sync_tag_embeddings(conn)

        # 3. メディアエントリインポート
        if entries:
            stats = import_entries(conn, entries)
            logger.info("メディアインポート完了:")
            for key, val in stats.items():
                if val:
                    logger.info("  %s: %d", key, val)

        # 4. 音声エントリインポート
        if audio_entries:
            audio_stats = import_audio_entries(conn, audio_entries)
            logger.info("音声インポート完了:")
            for key, val in audio_stats.items():
                if val:
                    logger.info("  %s: %d", key, val)

        # 5. 小説エントリインポート
        if novel_entries:
            novel_stats = import_novel_entries(conn, novel_entries)
            logger.info("小説インポート完了:")
            for key, val in novel_stats.items():
                if val:
                    logger.info("  %s: %d", key, val)

        # 6. desc_text + desc_embedding 補完（オプション）
        try:
            post_import_desc(conn)
        except ImportError as e:
            logger.info("desc 補完スキップ（モジュール未インストール: %s）", e)

    finally:
        conn.close()

    save_last_import(args.image_dir, run_time)


if __name__ == "__main__":
    main()
