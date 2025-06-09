from dataclasses import dataclass
from pathlib import Path

from lib.wd14tagger.tagger.interrogator.interrogator import AbsInterrogator
from lib.wd14tagger.tagger.interrogators import interrogators
from PIL import Image


@dataclass
class TagResult:
    model_name: str
    tags: dict[str, float]


def _image_interrogate(image_path: Path, model_name: str) -> dict[str, float]:
    interrogator = interrogators[model_name]
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        im.thumbnail((512, 512), Image.Resampling.LANCZOS)
        result = interrogator.interrogate(im)
    return AbsInterrogator.postprocess_tags(result[1])


def generate_tags(
    image_path: str,
    model_name: str = "wd-eva02-large-tagger-v3",
    use_all_models: bool = False,
) -> list[TagResult]:
    """
    画像からタグを生成。use_all_models=True で全モデルを使用。
    """
    image_path = Path(image_path)
    results = []

    model_list = interrogators.keys() if use_all_models else [model_name]

    for name in model_list:
        try:
            tags = _image_interrogate(image_path, name)
            if tags:
                results.append(TagResult(model_name=name, tags=tags))
        except Exception as e:
            print(f"[WARN] Skipped model '{name}' due to error: {e}")

    return results
