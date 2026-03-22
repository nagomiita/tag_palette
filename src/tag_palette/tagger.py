from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class TagResult:
    """タグ生成結果を格納するデータクラス。

    Attributes:
        model_name: 使用したモデル名
        tags: タグ名と信頼度のマッピング
        ratings: WD14 rating カテゴリと信頼度 (general, sensitive, questionable, explicit)
    """

    model_name: str
    tags: dict[str, float]
    ratings: dict[str, float] | None = None


def _load_image(image_path: Path) -> Image.Image:
    im = Image.open(image_path)
    im = im.convert("RGB")
    im.thumbnail((512, 512), Image.Resampling.LANCZOS)
    return im


def _image_interrogate(image_path: Path, model_name: str) -> tuple[dict[str, float], dict[str, float]]:
    from tag_palette._wd14tagger.interrogator.interrogator import AbsInterrogator
    from tag_palette._wd14tagger.interrogators import interrogators

    interrogator = interrogators[model_name]
    im = _load_image(image_path)
    ratings, tags = interrogator.interrogate(im)
    im.close()
    return AbsInterrogator.postprocess_tags(tags), ratings


def generate_tags(
    image_path: str | Path,
    model_name: str = "wd-eva02-large-tagger-v3",
    use_all_models: bool = False,
) -> list[TagResult]:
    """
    画像からタグを生成する。

    Parameters:
        image_path: 画像ファイルのパス
        model_name: 使用するモデル名 (デフォルト: wd-eva02-large-tagger-v3)
        use_all_models: True の場合、利用可能な全モデルで推論する

    Returns:
        TagResult のリスト。各要素にモデル名とタグ(信頼度付き)を含む。
    """
    from tag_palette._wd14tagger.interrogators import interrogators

    image_path = Path(image_path)
    results = []

    model_list = interrogators.keys() if use_all_models else [model_name]

    for name in model_list:
        try:
            tags, ratings = _image_interrogate(image_path, name)
            if tags:
                results.append(TagResult(model_name=name, tags=tags, ratings=ratings or None))
        except Exception as e:
            logger.warning("Skipped model '%s' due to error: %s", name, e)

    return results


def generate_tags_batch(
    image_paths: list[str | Path],
    model_name: str = "wd-eva02-large-tagger-v3",
    batch_size: int = 4,
    max_workers: int = 4,
    on_batch_done: Callable[[int, int], None] | None = None,
) -> list[TagResult]:
    """複数画像をバッチ処理でタグ生成する。

    前処理をスレッドプールで並列化し、ONNX推論をバッチ実行する。

    Parameters:
        image_paths: 画像ファイルパスのリスト
        model_name: 使用するモデル名
        batch_size: 1回の推論に含める画像数
        max_workers: 前処理の並列ワーカー数
        on_batch_done: バッチ完了時のコールバック (処理済み数, 全体数)

    Returns:
        TagResult のリスト（入力と同じ順序）。処理失敗した画像は tags が空。
    """
    from tag_palette._wd14tagger.interrogator.interrogator import AbsInterrogator
    from tag_palette._wd14tagger.interrogators import interrogators

    interrogator = interrogators[model_name]

    paths = [Path(p) for p in image_paths]
    total = len(paths)
    results: list[TagResult] = []

    for batch_start in range(0, total, batch_size):
        batch_paths = paths[batch_start : batch_start + batch_size]

        # 前処理を並列実行（PIL/OpenCV は C拡張で GIL を解放する）
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            images = list(executor.map(_load_image, batch_paths))

        try:
            batch_results = interrogator.interrogate_batch(images)
            for ratings, tags in batch_results:
                postprocessed = AbsInterrogator.postprocess_tags(tags)
                results.append(TagResult(model_name=model_name, tags=postprocessed, ratings=ratings or None))
        except Exception as e:
            logger.warning("Batch inference failed, falling back: %s", e)
            for img in images:
                try:
                    ratings, tags = interrogator.interrogate(img)
                    postprocessed = AbsInterrogator.postprocess_tags(tags)
                    results.append(TagResult(model_name=model_name, tags=postprocessed, ratings=ratings or None))
                except Exception as e2:
                    logger.warning("Skipped image due to error: %s", e2)
                    results.append(TagResult(model_name=model_name, tags={}))
        finally:
            for img in images:
                img.close()

        if on_batch_done:
            on_batch_done(min(batch_start + batch_size, total), total)

    return results
