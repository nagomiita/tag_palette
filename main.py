"""タスクスケジューラから呼び出す画像タグ生成スクリプト。

Eagle ライブラリの images ディレクトリをスキャンし、前回実行以降に追加された
画像に対してタグを生成し、Eagle の metadata.json に書き戻す。

前回実行時刻は状態ファイル (.last_run) に記録され、次回実行時に
それ以降に更新されたファイルのみを対象とする。

Usage:
    uv run python main.py --image-dir /path/to/eagle.library/images
    uv run python main.py --image-dir /path/to/eagle.library/images --model wd-eva02-large-tagger-v3
    uv run python main.py --image-dir /path/to/eagle.library/images --force
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

import numpy as np

from tag_palette import (
    generate_tags,
    load_tag_embeddings,
    load_translation_cache,
    save_tag_embeddings,
    save_translation_cache,
    tags_to_embedding,
    translate_tags,
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
THUMBNAIL_SIZE = (300, 300)
STATE_FILE = Path(".last_run")
SAVE_INTERVAL = 100

logger = logging.getLogger(__name__)


def setup_logging(log_file: Path | None = None) -> None:
    """ログ設定。ファイル指定時はファイルにも出力。"""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


# ── 前回実行時刻の管理 ──────────────────────────────────


def _state_path(image_dir: Path) -> Path:
    """image_dir の親ディレクトリ (eagle.library/) に .last_run ファイルを配置。"""
    return image_dir.parent / STATE_FILE


def load_last_run(image_dir: Path) -> datetime | None:
    """前回実行時刻を読み込む。初回は None。"""
    path = _state_path(image_dir)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return datetime.fromisoformat(text)
    except (ValueError, OSError):
        return None


def save_last_run(image_dir: Path, run_time: datetime) -> None:
    """実行時刻を状態ファイルに書き込む。"""
    path = _state_path(image_dir)
    path.write_text(run_time.isoformat(), encoding="utf-8")


# ── Eagle 画像探索 ──────────────────────────────────────


@dataclass
class EagleImage:
    """Eagle ライブラリの1画像エントリ。"""

    info_dir: Path  # {ID}.info ディレクトリ
    image_path: Path  # 元画像ファイルパス
    thumbnail_path: Path  # サムネイルパス ({name}_thumbnail.png)
    metadata_path: Path  # metadata.json パス
    eagle_id: str  # Eagle ID
    name: str  # 画像名
    ext: str  # 拡張子


def find_eagle_images(
    image_dir: Path,
    since: datetime | None,
    skip_processed: bool = True,
) -> list[EagleImage]:
    """Eagle images ディレクトリから対象画像を探索。

    - *.info/ ディレクトリを走査
    - metadata.json を読み取り、isDeleted=true / 既にタグ付き をスキップ
    - since 以降に更新されたもののみ対象 (since=None なら全件)
    """
    cutoff_ms = int(since.timestamp() * 1000) if since else 0

    images: list[EagleImage] = []
    for info_dir in sorted(image_dir.iterdir()):
        if not info_dir.is_dir() or not info_dir.name.endswith(".info"):
            continue

        metadata_path = info_dir / "metadata.json"
        if not metadata_path.exists():
            continue

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("metadata.json 読み込み失敗: %s -> %s", info_dir.name, e)
            continue

        # 削除済みはスキップ
        if meta.get("isDeleted", False):
            continue

        # 既処理スキップ (tag_palette.json が既にある場合)
        if skip_processed and (info_dir / "tag_palette.json").exists():
            continue

        # 更新時刻チェック (Eagle の mtime はミリ秒)
        mtime = meta.get("mtime", 0)
        if mtime <= cutoff_ms:
            continue

        # 画像ファイルを特定
        name = meta.get("name", "")
        ext = meta.get("ext", "")
        if not name or not ext:
            continue

        image_path = info_dir / f"{name}.{ext}"
        if not image_path.exists():
            logger.warning("ファイルが見つかりません: %s", image_path)
            continue

        eagle_id = meta.get("id", info_dir.name.replace(".info", ""))
        thumbnail_path = info_dir / f"{name}_thumbnail.png"
        images.append(
            EagleImage(
                info_dir=info_dir,
                image_path=image_path,
                thumbnail_path=thumbnail_path,
                metadata_path=metadata_path,
                eagle_id=eagle_id,
                name=name,
                ext=ext,
            )
        )

    return images


# ── サムネイル生成 ──────────────────────────────────────


def is_image_file(eagle_image: EagleImage) -> bool:
    """画像ファイルかどうかを判定する。"""
    return f".{eagle_image.ext}".lower() in IMAGE_EXTENSIONS


def ensure_thumbnail(eagle_image: EagleImage) -> None:
    """サムネイルが存在しなければ生成する。画像は PIL、動画は ffmpeg を使用。"""
    if eagle_image.thumbnail_path.exists():
        return
    if is_image_file(eagle_image):
        try:
            with Image.open(eagle_image.image_path) as img:
                img = img.convert("RGB")
                img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                img.save(eagle_image.thumbnail_path, "PNG")
            logger.info("サムネイル生成 (画像): %s", eagle_image.thumbnail_path.name)
        except Exception as e:
            logger.error("サムネイル生成失敗: %s -> %s", eagle_image.eagle_id, e)
    else:
        try:
            w, h = THUMBNAIL_SIZE
            subprocess.run(
                [
                    "ffmpeg", "-i", str(eagle_image.image_path),
                    "-vframes", "1",
                    "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease",
                    str(eagle_image.thumbnail_path),
                ],
                capture_output=True,
                check=True,
            )
            logger.info("サムネイル生成 (動画): %s", eagle_image.thumbnail_path.name)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error("動画サムネイル生成失敗: %s -> %s", eagle_image.eagle_id, e)


# ── Eagle metadata.json への書き戻し ────────────────────


def write_tags_to_eagle(
    eagle_image: EagleImage,
    tags: dict[str, float],
    model_name: str,
) -> None:
    """タグの日本語訳を Eagle の metadata.json の annotation に書き込み、
    tag_palette.json にタグ生データを保存する。"""
    tag_names = list(tags.keys())
    ja_tags = translate_tags(tag_names)

    # Eagle metadata.json に annotation 書き込み
    try:
        with open(eagle_image.metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        meta["annotation"] = ", ".join(ja_tags)

        with open(eagle_image.metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except Exception as e:
        logger.error("metadata.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    # 埋め込みベクトル生成 → .npy 保存
    try:
        embedding_bytes = tags_to_embedding(tags)
        if embedding_bytes:
            embedding_arr = np.frombuffer(embedding_bytes, dtype=np.float32)
            npy_path = eagle_image.info_dir / "embedding.npy"
            np.save(npy_path, embedding_arr)
    except Exception as e:
        logger.error("埋め込み生成失敗: %s -> %s", eagle_image.eagle_id, e)

    # tag_palette.json にタグ生データ保存
    try:
        tp_path = eagle_image.info_dir / "tag_palette.json"
        tp_data = {
            "image_id": eagle_image.eagle_id,
            "image_name": eagle_image.image_path.name,
            "thumbnail_name": eagle_image.thumbnail_path.name,
            "ext": eagle_image.ext,
            "model_name": model_name,
            "tags": tags,
            "tags_ja": dict(zip(tag_names, ja_tags)),
            "generated_at": datetime.now().isoformat(),
        }
        with open(tp_path, "w", encoding="utf-8") as f:
            json.dump(tp_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("tag_palette.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)


# ── メイン ──────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Eagle ライブラリの画像にタグを生成 (タスクスケジューラ用)"
    )
    parser.add_argument(
        "--image-dir",
        type=Path,
        required=True,
        help="Eagle ライブラリの images ディレクトリ",
    )
    parser.add_argument("--log-file", type=Path, default=None, help="ログファイルパス")
    parser.add_argument(
        "--model", default="wd-eva02-large-tagger-v3", help="使用するモデル名"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="全画像を再処理する (タグ付き画像もスキップしない)",
    )
    args = parser.parse_args()

    setup_logging(args.log_file)

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
        ensure_thumbnail(eagle_image)

        # サムネイルが無ければスキップ
        if not eagle_image.thumbnail_path.exists():
            logger.warning("サムネイルが見つかりません (スキップ): %s", eagle_image.eagle_id)
            continue

        try:
            tag_results = generate_tags(eagle_image.thumbnail_path, model_name=args.model)
            if tag_results:
                write_tags_to_eagle(
                    eagle_image,
                    tag_results[0].tags,
                    tag_results[0].model_name,
                )
                processed += 1
                if processed % SAVE_INTERVAL == 0:
                    save_translation_cache()
                    save_tag_embeddings()
                    logger.info("キャッシュ保存 (%d件処理済み)", processed)
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
