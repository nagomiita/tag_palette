from dataclasses import dataclass
from pathlib import Path

from lib.wd14tagger.tagger.interrogator.interrogator import AbsInterrogator
from lib.wd14tagger.tagger.interrogators import interrogators
from PIL import Image

MODEL_NAME: str = "wd-eva02-large-tagger-v3"


@dataclass
class TagResult:
    model_name: str
    tags: dict[str, float]


def _image_interrogate(image_path: Path) -> dict[str, float]:
    """
    Predictions from a image path
    """
    interrogator = interrogators[MODEL_NAME]
    with Image.open(image_path) as im:
        result = interrogator.interrogate(im)

    return AbsInterrogator.postprocess_tags(
        result[1],
    )


def generate_tags(image_path: str) -> TagResult:
    tags = _image_interrogate(Path(image_path))
    if not tags:
        raise ValueError("No tags generated from the image.")
    return TagResult(model_name=MODEL_NAME, tags=tags)
