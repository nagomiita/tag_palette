"""
Interrogator for the Camie-Tagger model.
reference:
https://huggingface.co/Camais03/camie-tagger/blob/main/onnx_inference.py
"""
import sys
import json
import numpy as np

from PIL import Image
from huggingface_hub import hf_hub_download
from onnxruntime import InferenceSession

from tag_palette._wd14tagger.interrogator.interrogator import AbsInterrogator

class CamieTaggerInterrogator(AbsInterrogator):
    repo_id: str
    model_path: str
    tags_path: str

    def __init__(
        self,
        name: str,
        repo_id: str,
        model_path: str,
        tags_path='metadata.json',
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

        self.model = InferenceSession(model_path,
                                        providers=self.providers)
        print(f'Loaded {self.name} model from {model_path}', file=sys.stderr)

        with open(tags_path, 'r', encoding='utf-8') as filen:
            self.metadata = json.load(filen)

        if self.name == "Camie Tagger v2":
            self.metadata['idx_to_tag'] = self.metadata['dataset_info']['tag_mapping']['idx_to_tag']
            self.metadata['tag_to_category'] = self.metadata['dataset_info']['tag_mapping']['tag_to_category']

    def preprocess(self, image: Image.Image) -> np.ndarray:
        img_array_chw = preprocess_image(image)
        return img_array_chw

    def _postprocess_output(self, outputs: list[np.ndarray], batch_index: int = 0) -> tuple[dict[str, float], dict[str, float]]:
        initial_probs = 1.0 / (1.0 + np.exp(-outputs[0]))
        refined_probs = 1.0 / (1.0 + np.exp(-outputs[1])) if len(outputs) > 1 else initial_probs

        all_tags = {}
        for idx_str, tag_name in self.metadata['idx_to_tag'].items():
            idx = int(idx_str)
            prob = float(refined_probs[batch_index, idx])
            all_tags[tag_name] = prob

        rating_tags = {}
        other_tags = {}
        for tag_name, prob in all_tags.items():
            category = self.metadata['tag_to_category'].get(tag_name, "general")
            if category == 'rating':
                rating_tags[tag_name] = prob
            else:
                other_tags[tag_name] = prob

        return rating_tags, other_tags

    def interrogate(
        self,
        image: Image.Image
    ) -> tuple[
        dict[str, float],  # rating confidents
        dict[str, float]  # tag confidents
    ]:
        if self.model is None:
            self.load()
        if self.model is None:
            raise Exception("Model not loading.")

        img_numpy = np.expand_dims(self.preprocess(image), axis=0)

        input_ = self.model.get_inputs()[0]
        if input_.type == 'tensor(float)':
            img_numpy = img_numpy.astype(np.float32)

        outputs = self.model.run(None, {input_.name: img_numpy})
        return self._postprocess_output(outputs)

    def interrogate_batch(
        self,
        images: list[Image.Image]
    ) -> list[tuple[dict[str, float], dict[str, float]]]:
        if self.model is None:
            self.load()
        if self.model is None:
            raise Exception("Model not loading.")

        batch = np.stack([self.preprocess(img) for img in images])

        input_ = self.model.get_inputs()[0]
        if input_.type == 'tensor(float)':
            batch = batch.astype(np.float32)

        try:
            outputs = self.model.run(None, {input_.name: batch})
        except Exception:
            return [self.interrogate(img) for img in images]

        return [self._postprocess_output(outputs, batch_index=i) for i in range(len(images))]

def preprocess_image(img: Image.Image, image_size: int = 512) -> np.ndarray:
    """Process a PIL image for inference using NumPy."""
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    width, height = img.size
    aspect_ratio = width / height

    if aspect_ratio > 1:
        new_width = image_size
        new_height = int(new_width / aspect_ratio)
    else:
        new_height = image_size
        new_width = int(new_height * aspect_ratio)

    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    new_image = Image.new('RGB', (image_size, image_size), (0, 0, 0))
    paste_x = (image_size - new_width) // 2
    paste_y = (image_size - new_height) // 2
    new_image.paste(img, (paste_x, paste_y))

    img_array = np.array(new_image, dtype=np.float32)
    img_array /= 255.0
    img_array = img_array.transpose((2, 0, 1))

    return img_array
