"""
Interrogator for the PixAI Tagger model.
reference:
https://huggingface.co/deepghs/pixai-tagger-v0.9-onnx
"""
import sys

import numpy as np
import pandas as pd
from PIL import Image
from huggingface_hub import hf_hub_download

from tag_palette._wd14tagger.interrogator.interrogator import AbsInterrogator


class PixAITaggerInterrogator(AbsInterrogator):
    """PixAI Tagger interrogator.

    EVA02 ベースのタグ推定モデル。WD v3 より新しい Danbooru データで学習。
    入力: 448x448 RGB, normalize(mean=0.5, std=0.5), NCHW
    出力: sigmoid 適用前の logits
    """

    def __init__(
        self,
        name: str,
        repo_id: str,
        model_path: str = 'model.onnx',
        tags_path: str = 'selected_tags.csv',
        image_size: int = 448,
    ) -> None:
        super().__init__(name)
        self.repo_id = repo_id
        self.model_path = model_path
        self.tags_path = tags_path
        self.image_size = image_size
        self.tags = None
        self.model = None

    def download(self) -> tuple[str, str]:
        print(f"Loading {self.name} model file from {self.repo_id}", file=sys.stderr)

        model_path = hf_hub_download(
            repo_id=self.repo_id,
            filename=self.model_path,
        )
        tags_path = hf_hub_download(
            repo_id=self.repo_id,
            filename=self.tags_path,
        )
        return model_path, tags_path

    def load(self) -> None:
        model_path, tags_path = self.download()

        from onnxruntime import InferenceSession
        self.model = InferenceSession(model_path, providers=self.providers)
        print(f'Loaded {self.name} model from {model_path}', file=sys.stderr)

        self.tags = pd.read_csv(tags_path)

    def preprocess(self, image: Image.Image) -> np.ndarray:
        """448x448 にリサイズ、[0,1] → normalize(0.5, 0.5)、NCHW 形式。"""
        if image.mode in ('RGBA', 'P'):
            image = image.convert('RGB')
        elif image.mode != 'RGB':
            image = image.convert('RGB')

        image = image.resize(
            (self.image_size, self.image_size),
            Image.Resampling.BILINEAR,
        )

        img_array = np.array(image, dtype=np.float32) / 255.0
        # normalize: (x - 0.5) / 0.5
        img_array = (img_array - 0.5) / 0.5
        # HWC -> CHW
        img_array = img_array.transpose((2, 0, 1))
        return img_array

    def _postprocess_output(
        self, logits: np.ndarray
    ) -> tuple[dict[str, float], dict[str, float]]:
        if self.tags is None:
            raise Exception("Tags not loaded.")

        # sigmoid
        probs = 1.0 / (1.0 + np.exp(-logits))

        tag_names = self.tags['name'].tolist()
        tags = {
            name: float(prob)
            for name, prob in zip(tag_names, probs)
        }
        # PixAI モデルには rating タグがないため空 dict を返す
        return {}, tags

    def interrogate(
        self,
        image: Image.Image,
    ) -> tuple[
        dict[str, float],  # rating confidents
        dict[str, float],  # tag confidents
    ]:
        if self.model is None:
            self.load()
        if self.model is None:
            raise Exception("Model not loaded.")

        x = np.expand_dims(self.preprocess(image), 0)

        input_ = self.model.get_inputs()[0]
        output = self.model.get_outputs()[0]
        y = self.model.run([output.name], {input_.name: x})[0]

        return self._postprocess_output(y[0])

    def interrogate_batch(
        self,
        images: list[Image.Image],
    ) -> list[tuple[dict[str, float], dict[str, float]]]:
        if self.model is None:
            self.load()
        if self.model is None:
            raise Exception("Model not loaded.")

        batch = np.stack([self.preprocess(img) for img in images])

        input_ = self.model.get_inputs()[0]
        output = self.model.get_outputs()[0]

        try:
            y = self.model.run([output.name], {input_.name: batch})[0]
        except Exception:
            return [self.interrogate(img) for img in images]

        return [self._postprocess_output(y[i]) for i in range(len(images))]
