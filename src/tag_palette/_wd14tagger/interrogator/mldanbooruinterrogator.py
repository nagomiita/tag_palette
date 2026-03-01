import sys
import json

from PIL import Image
from numpy import asarray, float32, expand_dims, exp

from huggingface_hub import hf_hub_download

from tag_palette._wd14tagger.interrogator.interrogator import AbsInterrogator
import tag_palette._wd14tagger.dbimutils as dbimutils

class MLDanbooruInterrogator(AbsInterrogator):
    """ Interrogator for the MLDanbooru model. """
    def __init__(
        self,
        name: str,
        repo_id: str,
        model_path: str,
        tags_path='classes.json',
    ) -> None:
        super().__init__(name)
        self.model_path = model_path
        self.tags_path = tags_path
        self.repo_id = repo_id
        self.tags = None
        self.model = None

    def download(self) -> tuple[str, str]:
        print(f"Loading {self.name} model file from {self.repo_id}", file=sys.stderr)

        model_path = hf_hub_download(
            repo_id=self.repo_id,
            filename=self.model_path
        )
        tags_path = hf_hub_download(
            repo_id=self.repo_id,
            filename=self.tags_path,
        )
        return model_path, tags_path

    def load(self) -> None:
        model_path, tags_path = self.download()

        from onnxruntime import InferenceSession
        self.model = InferenceSession(model_path,
                                        providers=self.providers)
        print(f'Loaded {self.name} model from {model_path}', file=sys.stderr)

        with open(tags_path, 'r', encoding='utf-8') as filen:
            self.tags = json.load(filen)

    def preprocess(self, image: Image.Image) -> 'float32':
        image = dbimutils.fill_transparent(image)
        image = dbimutils.resize(image, 448)
        x = asarray(image, dtype=float32) / 255
        # HWC -> CHW
        return x.transpose((2, 0, 1))

    def _postprocess_output(self, y: 'float32') -> tuple[dict[str, float], dict[str, float]]:
        y = 1 / (1 + exp(-y))
        if self.tags is None:
            raise Exception("Tags not loading.")
        tags = {tag: float(conf) for tag, conf in zip(self.tags, y.flatten())}
        return {}, tags

    def interrogate(
        self,
        image: Image.Image
    ) -> tuple[
        dict[str, float],  # rating confidents
        dict[str, float]  # tag confidents
    ]:
        if self.model is None:
            self.load()

        x = expand_dims(self.preprocess(image), 0)

        input_ = self.model.get_inputs()[0]
        output = self.model.get_outputs()[0]
        y, = self.model.run([output.name], {input_.name: x})

        return self._postprocess_output(y[0])

    def interrogate_batch(
        self,
        images: list[Image.Image]
    ) -> list[tuple[dict[str, float], dict[str, float]]]:
        if self.model is None:
            self.load()

        from numpy import stack
        batch = stack([self.preprocess(img) for img in images])

        input_ = self.model.get_inputs()[0]
        output = self.model.get_outputs()[0]

        try:
            y, = self.model.run([output.name], {input_.name: batch})
        except Exception:
            return [self.interrogate(img) for img in images]

        return [self._postprocess_output(y[i]) for i in range(len(images))]
