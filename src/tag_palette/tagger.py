from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class TagResult:
    """タグ生成結果を格納するデータクラス。

    Attributes:
        model_name: 使用したモデル名
        tags: タグ名と信頼度のマッピング
    """

    model_name: str
    tags: dict[str, float]


def _image_interrogate(image_path: Path, model_name: str) -> dict[str, float]:
    from lib.wd14tagger.tagger.interrogator.interrogator import AbsInterrogator
    from lib.wd14tagger.tagger.interrogators import interrogators

    interrogator = interrogators[model_name]
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        im.thumbnail((512, 512), Image.Resampling.LANCZOS)
        result = interrogator.interrogate(im)
    return AbsInterrogator.postprocess_tags(result[1])


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

    Raises:
        ImportError: lib.wd14tagger がインストールされていない場合
    """
    from lib.wd14tagger.tagger.interrogators import interrogators

    image_path = Path(image_path)
    results = []

    model_list = interrogators.keys() if use_all_models else [model_name]

    for name in model_list:
        try:
            tags = _image_interrogate(image_path, name)
            if tags:
                results.append(TagResult(model_name=name, tags=tags))
        except Exception as e:
            logger.warning("Skipped model '%s' due to error: %s", name, e)

    return results
