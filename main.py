"""タスクスケジューラから呼び出すメディアタグ生成スクリプト。

Eagle ライブラリの images ディレクトリをスキャンし、前回実行以降に追加された
画像・音声に対してタグを生成し、Eagle の metadata.json に書き戻す。

- 画像: WD14 Tagger でタグ生成
- 音声: PANNs で分類タグ生成 (Voice は Whisper で文字起こし)

前回実行時刻は状態ファイル (.last_run) に記録され、次回実行時に
それ以降に更新されたファイルのみを対象とする。

Usage:
    uv run python main.py --image-dir /path/to/eagle.library/images
    uv run python main.py --image-dir /path/to/eagle.library/images --model EVA02_Large
    uv run python main.py --image-dir /path/to/eagle.library/images --force
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from tag_palette import (
    generate_tags,
    load_tag_embeddings,
    load_translation_cache,
    save_tag_embeddings,
    save_translation_cache,
)
from tag_palette.audio.tag_writer import write_audio_tags_to_eagle
from tag_palette.media.eagle_scanner import (
    find_eagle_images,
    is_eagle_audio_file,
    is_eagle_novel_file,
    is_manga_image,
)
from tag_palette.media.image_processor import convert_heic_to_webp, ensure_thumbnail
from tag_palette.media.tag_writer import write_tags_to_eagle
from tag_palette.shared.run_state import (
    load_last_run,
    save_last_run,
    setup_logging,
)

SAVE_INTERVAL = 100

logger = logging.getLogger(__name__)


# ── メイン ──────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Eagle ライブラリの画像にタグを生成 (タスクスケジューラ用)"
    )
    from tag_palette.shared.env_config import get_image_dir

    parser.add_argument(
        "--image-dir",
        type=Path,
        default=get_image_dir(),
        help="Eagle ライブラリの images ディレクトリ (env: EAGLE_IMAGE_DIR)",
    )
    parser.add_argument("--log-file", type=Path, default=None, help="ログファイルパス")
    parser.add_argument(
        "--model", default="EVA02_Large", help="使用するモデル名"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="全画像を再処理する (タグ付き画像もスキップしない)",
    )
    args = parser.parse_args()

    setup_logging(args.log_file)

    if not args.image_dir:
        parser.error("--image-dir または環境変数 EAGLE_IMAGE_DIR を指定してください")
    if not args.image_dir.is_dir():
        logger.error("ディレクトリが見つかりません: %s", args.image_dir)
        sys.exit(1)

    # 今回の実行時刻を記録 (探索前に取得)
    run_time = datetime.now()

    # 前回実行時刻
    if args.force:
        since = None
        logger.info("--force: 全画像を対象にします")
    else:
        since = load_last_run(args.image_dir)
        if since:
            logger.info("前回実行: %s", since.isoformat())
        else:
            logger.info("初回実行: 全画像を対象にします")

    # キャッシュ読み込み
    load_translation_cache()
    load_tag_embeddings()

    # Eagle 画像探索
    images = find_eagle_images(
        args.image_dir, since=since, skip_processed=not args.force
    )
    logger.info("対象画像数: %d", len(images))

    if not images:
        logger.info("処理対象の画像がありません。")
        save_last_run(args.image_dir, run_time)
        return

    # タグ生成 → Eagle に書き戻し
    start = time.perf_counter()
    processed = 0

    for i, eagle_image in enumerate(images, 1):
        logger.info("(%d/%d) %s", i, len(images), eagle_image.image_path.name)

        if is_eagle_audio_file(eagle_image):
            # ── 音声処理 ──
            try:
                from tag_palette.audio.tagger import detect_type_from_path, generate_audio_tags

                audio_type_override = detect_type_from_path(eagle_image.image_path)
                audio_result = generate_audio_tags(
                    eagle_image.image_path,
                    audio_type_override=audio_type_override,
                )
                write_audio_tags_to_eagle(eagle_image, audio_result)
                processed += 1
                logger.info(
                    "  Audio: %s (%s, %dms)",
                    audio_result.audio_type.value,
                    audio_result.model_name,
                    audio_result.duration_ms or 0,
                )
            except Exception as e:
                logger.error("Failed (audio): %s -> %s", eagle_image.eagle_id, e)
        elif is_eagle_novel_file(eagle_image):
            # ── 小説処理 ──
            try:
                from tag_palette.novel.tag_writer import write_novel_to_eagle

                novel_info = write_novel_to_eagle(eagle_image)
                processed += 1
                logger.info(
                    "  Novel: %s (%s, %d chunks, %d morphemes)",
                    novel_info["title"],
                    novel_info["author"],
                    novel_info["num_chunks"],
                    novel_info["num_morphemes"],
                )
            except Exception as e:
                logger.error("Failed (novel): %s -> %s", eagle_image.eagle_id, e)
        else:
            # ── 画像/動画処理 ──
            convert_heic_to_webp(eagle_image)
            ensure_thumbnail(eagle_image)

            # サムネイルが無ければスキップ
            if not eagle_image.thumbnail_path.exists():
                logger.warning(
                    "サムネイルが見つかりません (スキップ): %s", eagle_image.eagle_id
                )
                continue

            try:
                tag_results = generate_tags(
                    eagle_image.thumbnail_path, model_name=args.model
                )
                if tag_results:
                    write_tags_to_eagle(
                        eagle_image,
                        tag_results[0].tags,
                        tag_results[0].model_name,
                        ratings=tag_results[0].ratings,
                    )
                    processed += 1
                    if processed % SAVE_INTERVAL == 0:
                        save_translation_cache()
                        save_tag_embeddings()
                        logger.info("キャッシュ保存 (%d件処理済み)", processed)

                    # 漫画判定 → 追加OCR
                    if is_manga_image(eagle_image.image_path, tag_results[0].tags):
                        try:
                            from tag_palette.manga.tag_writer import write_manga_to_eagle

                            manga_info = write_manga_to_eagle(
                                eagle_image, model_name=args.model,
                            )
                            logger.info(
                                "  Manga OCR: %d panels, %d texts%s",
                                manga_info["num_panels"],
                                manga_info["num_texts"],
                                f" [{manga_info['ocr_preview']}]" if manga_info.get("ocr_preview") else "",
                            )
                        except Exception as e:
                            logger.error("Failed (manga OCR): %s -> %s", eagle_image.eagle_id, e)
            except Exception as e:
                logger.error("Failed: %s -> %s", eagle_image.eagle_id, e)

    elapsed = time.perf_counter() - start
    logger.info(
        "完了: %d/%d 件 (%.2fs, %.2fs/image)",
        processed,
        len(images),
        elapsed,
        elapsed / max(len(images), 1),
    )

    # キャッシュ保存
    save_translation_cache()
    save_tag_embeddings()

    # 実行時刻を記録
    save_last_run(args.image_dir, run_time)


if __name__ == "__main__":
    main()
