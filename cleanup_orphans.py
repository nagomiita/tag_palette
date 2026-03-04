"""オリジナルファイルが存在しない .info ディレクトリを退避するスクリプト。

Eagle ライブラリの images ディレクトリを走査し、metadata.json に記載された
オリジナルファイル ({name}.{ext}) が存在しないディレクトリを
指定した退避先に移動する。確認後に手動で削除する想定。

Usage:
    uv run python cleanup_orphans.py --image-dir /path/to/eagle.library/images
    uv run python cleanup_orphans.py --image-dir /path/to/eagle.library/images --dest /path/to/orphans
    uv run python cleanup_orphans.py --image-dir /path/to/eagle.library/images --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


PROGRESS_INTERVAL = 1000


def find_orphan_dirs(image_dir: Path) -> list[tuple[Path, str]]:
    """オリジナルファイルが存在しない .info ディレクトリを探索する。

    Returns:
        (info_dir, 理由) のリスト
    """
    orphans: list[tuple[Path, str]] = []
    scanned = 0

    logger.info("ディレクトリ列挙中... (SMB 経由の場合は数分かかることがあります)")
    for entry in os.scandir(image_dir):
        if not entry.is_dir() or not entry.name.endswith(".info"):
            continue

        scanned += 1
        if scanned % PROGRESS_INTERVAL == 0:
            logger.info("走査中... %d 件 (孤立: %d 件)", scanned, len(orphans))

        info_dir = Path(entry.path)
        metadata_path = info_dir / "metadata.json"
        if not metadata_path.exists():
            orphans.append((info_dir, "metadata.json が存在しない"))
            continue

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            orphans.append((info_dir, "metadata.json の読み込み失敗"))
            continue

        name = meta.get("name", "")
        ext = meta.get("ext", "")
        if not name or not ext:
            orphans.append((info_dir, "name または ext が空"))
            continue

        image_path = info_dir / f"{name}.{ext}"
        if not image_path.exists():
            orphans.append((info_dir, f"ファイル未検出: {name}.{ext}"))

    logger.info("走査完了: %d 件 (孤立: %d 件)", scanned, len(orphans))
    return orphans


def move_orphans(
    orphans: list[tuple[Path, str]], dest_dir: Path, dry_run: bool = False
) -> int:
    """孤立ディレクトリを退避先に移動する。"""
    if not orphans:
        logger.info("孤立ディレクトリはありません。")
        return 0

    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    for info_dir, reason in orphans:
        target = dest_dir / info_dir.name
        if dry_run:
            logger.info("[DRY-RUN] %s -> %s (%s)", info_dir.name, target, reason)
        else:
            try:
                shutil.move(str(info_dir), str(target))
                logger.info("移動: %s -> %s (%s)", info_dir.name, target, reason)
            except Exception as e:
                logger.error("移動失敗: %s -> %s", info_dir.name, e)
                continue
        moved += 1

    return moved


def main() -> None:
    from env_config import get_image_dir

    parser = argparse.ArgumentParser(
        description="オリジナルファイルが存在しない .info ディレクトリを退避"
    )
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=get_image_dir(),
        help="Eagle ライブラリの images ディレクトリ (env: EAGLE_IMAGE_DIR)",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="退避先ディレクトリ (デフォルト: eagle.library/_orphans)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際には移動せず対象を表示するのみ",
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

    dest_dir = args.dest or (args.image_dir.parent / "_orphans")

    logger.info("走査開始: %s", args.image_dir)
    orphans = find_orphan_dirs(args.image_dir)
    logger.info("孤立ディレクトリ数: %d", len(orphans))

    if not orphans:
        return

    moved = move_orphans(orphans, dest_dir, dry_run=args.dry_run)
    logger.info("完了: %d 件%s", moved, " (dry-run)" if args.dry_run else "")


if __name__ == "__main__":
    main()
