"""画像変換・サムネイル生成。"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from PIL import Image

from tag_palette.media.eagle_scanner import EagleImage, is_image_file

logger = logging.getLogger(__name__)

THUMBNAIL_SIZE = (300, 300)


def convert_heic_to_webp(eagle_image: EagleImage, quality: int = 90) -> None:
    """HEIC 画像を WebP に変換し、metadata.json を更新、元ファイルを削除する。"""
    if eagle_image.ext.lower() != "heic":
        return

    from pillow_heif import register_heif_opener
    register_heif_opener()

    webp_path = eagle_image.info_dir / f"{eagle_image.name}.webp"
    try:
        with Image.open(eagle_image.image_path) as img:
            img.save(webp_path, "WEBP", quality=quality)

        # metadata.json の ext を更新
        with open(eagle_image.metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["ext"] = "webp"
        with open(eagle_image.metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        # 元ファイル削除
        eagle_image.image_path.unlink()

        # EagleImage を更新
        eagle_image.ext = "webp"
        eagle_image.image_path = webp_path

        logger.info("HEIC → WebP 変換: %s", webp_path.name)
    except Exception as e:
        logger.error("HEIC 変換失敗: %s -> %s", eagle_image.eagle_id, e)
        # 中途半端な webp が残っていたら削除
        if webp_path.exists() and eagle_image.image_path.exists():
            webp_path.unlink()


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
                    "ffmpeg",
                    "-i",
                    str(eagle_image.image_path),
                    "-vframes",
                    "1",
                    "-vf",
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease",
                    str(eagle_image.thumbnail_path),
                ],
                capture_output=True,
                check=True,
            )
            logger.info("サムネイル生成 (動画): %s", eagle_image.thumbnail_path.name)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error("動画サムネイル生成失敗: %s -> %s", eagle_image.eagle_id, e)
