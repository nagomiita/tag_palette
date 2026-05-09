"""Eagle ライブラリのファイル探索とファイルタイプ判定。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".psd"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus"}
NOVEL_EXTENSIONS = {".txt", ".pdf"}
HTML_EXTENSIONS = {".html", ".htm"}


_MANGA_TAGS = {"漫画", "manga", "comic", "コミック"}
_MANGA_FOLDER_NAMES = {"漫画", "manga", "comic", "comics", "コミック"}


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
    eagle_tags: list[str] = field(default_factory=list)  # Eagle metadata の tags
    eagle_folders: list[str] = field(default_factory=list)  # Eagle metadata の folders 名


def is_image_file(eagle_image: EagleImage) -> bool:
    """画像ファイルかどうかを判定する。"""
    return f".{eagle_image.ext}".lower() in IMAGE_EXTENSIONS


def is_eagle_audio_file(eagle_image: EagleImage) -> bool:
    """音声ファイルかどうかを判定する。"""
    return f".{eagle_image.ext}".lower() in AUDIO_EXTENSIONS


def is_eagle_novel_file(eagle_image: EagleImage) -> bool:
    """小説ファイルかどうかを判定する。"""
    return f".{eagle_image.ext}".lower() in NOVEL_EXTENSIONS


_COMIC_WD14_TAGS = {"comic", "speech_bubble", "4koma", "manga_(medium)"}


def is_manga_image(
    image_path: str | Path,
    wd14_tags: dict[str, float] | None = None,
    *,
    classify_threshold: float = 0.5,
    tag_threshold: float = 0.3,
) -> bool:
    """画像が漫画ページかどうかを判定する。

    anime_classify の comic スコアをメインに、WD14 タグをフォールバックとして使用。

    Parameters:
        image_path: 画像パス (anime_classify に渡す)
        wd14_tags: WD14 タグ付け結果 (あれば)
        classify_threshold: anime_classify の comic スコア閾値
        tag_threshold: WD14 タグの信頼度閾値

    Returns:
        漫画なら True
    """
    # 1. anime_classify で判定
    try:
        from imgutils.validate import anime_classify_score
        scores = anime_classify_score(str(image_path))
        if scores.get("comic", 0) >= classify_threshold:
            return True
    except Exception:
        pass

    # 2. WD14 タグでフォールバック
    if wd14_tags:
        for tag in _COMIC_WD14_TAGS:
            if wd14_tags.get(tag, 0) >= tag_threshold:
                return True

    return False


def is_eagle_html_file(eagle_image: EagleImage) -> bool:
    """HTMLファイルかどうかを判定する。"""
    return f".{eagle_image.ext}".lower() in HTML_EXTENSIONS


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
    cutoff = since.timestamp() if since else 0

    images: list[EagleImage] = []
    for info_dir in sorted(image_dir.iterdir()):
        if not info_dir.is_dir() or not info_dir.name.endswith(".info"):
            continue

        # フォルダ作成日時チェック (= Eagle へのインポート日時) を最初に行う
        st = info_dir.stat()
        ctime = getattr(st, "st_birthtime", st.st_ctime)
        if ctime < cutoff:
            continue

        # 既処理スキップ (tag_palette.json が既にある場合)
        if skip_processed and (info_dir / "tag_palette.json").exists():
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
        eagle_tags = meta.get("tags", [])
        eagle_folders = [f.get("name", "") for f in meta.get("folders", []) if isinstance(f, dict)]
        if not eagle_folders:
            # folders が文字列リストの場合
            eagle_folders = [f for f in meta.get("folders", []) if isinstance(f, str)]
        images.append(
            EagleImage(
                info_dir=info_dir,
                image_path=image_path,
                thumbnail_path=thumbnail_path,
                metadata_path=metadata_path,
                eagle_id=eagle_id,
                name=name,
                ext=ext,
                eagle_tags=eagle_tags,
                eagle_folders=eagle_folders,
            )
        )

    return images
