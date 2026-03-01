import os
import sys
import pandas as pd
import numpy as np

from typing import Tuple, Dict
from PIL import Image

from pathlib import Path
from huggingface_hub import hf_hub_download
import re

tag_escape_pattern = re.compile(r'([\\()])')

from tag_palette._wd14tagger.interrogator.interrogator import AbsInterrogator
import tag_palette._wd14tagger.dbimutils as dbimutils

class WaifuDiffusionInterrogator(AbsInterrogator):
    def __init__(
        self,
        name: str,
        model_path='model.onnx',
        tags_path='selected_tags.csv',
        **kwargs
    ) -> None:
        super().__init__(name)
        self.model_path = model_path
        self.tags_path = tags_path
        self.kwargs = kwargs

    def download(self) -> Tuple[os.PathLike, os.PathLike]:
        print(f"Loading {self.name} model file from {self.kwargs['repo_id']}", file=sys.stderr)

        model_path = Path(hf_hub_download(
            **self.kwargs, filename=self.model_path))
        tags_path = Path(hf_hub_download(
            **self.kwargs, filename=self.tags_path))
        return model_path, tags_path

    def load(self) -> None:
        model_path, tags_path = self.download()

        from onnxruntime import InferenceSession
        self.model = InferenceSession(str(model_path), providers=self.providers)

        print(f'Loaded {self.name} model from {model_path}', file=sys.stderr)

        self.tags = pd.read_csv(tags_path)

    def preprocess(self, input_image: Image.Image) -> np.ndarray:
        if not hasattr(self, 'model') or self.model is None:
            self.load()
        _, height, _, _ = self.model.get_inputs()[0].shape

        image = input_image.convert('RGBA')
        new_image = Image.new('RGBA', image.size, 'WHITE')
        new_image.paste(image, mask=image)
        image = new_image.convert('RGB')
        image = np.asarray(image)
        # PIL RGB to OpenCV BGR
        image = image[:, :, ::-1]
        image = dbimutils.make_square(image, height)
        image = dbimutils.smart_resize(image, height)
        return image.astype(np.float32)

    def _postprocess_output(self, confidents: np.ndarray) -> tuple[dict[str, float], dict[str, float]]:
        if self.tags is None:
            raise Exception("Tags not loading.")
        tags = self.tags[:][['name']]
        tags['confidents'] = confidents
        ratings = dict(tags[:4].values)
        tags = dict(tags[4:].values)
        return ratings, tags

    def interrogate(
        self,
        input_image: Image.Image
    ) -> tuple[
        dict[str, float],  # rating confidents
        dict[str, float]  # tag confidents
    ]:
        if not hasattr(self, 'model') or self.model is None:
            self.load()
        if self.model is None:
            raise Exception("Model not loading.")

        image = np.expand_dims(self.preprocess(input_image), 0)

        input_name = self.model.get_inputs()[0].name
        label_name = self.model.get_outputs()[0].name
        confidents = self.model.run([label_name], {input_name: image})[0]

        return self._postprocess_output(confidents[0])

    def interrogate_batch(
        self,
        images: list[Image.Image]
    ) -> list[tuple[dict[str, float], dict[str, float]]]:
        if not hasattr(self, 'model') or self.model is None:
            self.load()
        if self.model is None:
            raise Exception("Model not loading.")

        batch = np.stack([self.preprocess(img) for img in images])

        input_name = self.model.get_inputs()[0].name
        label_name = self.model.get_outputs()[0].name

        try:
            confidents = self.model.run([label_name], {input_name: batch})[0]
        except Exception:
            return [self.interrogate(img) for img in images]

        return [self._postprocess_output(confidents[i]) for i in range(len(images))]
