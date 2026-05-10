from __future__ import annotations

import base64
import logging
from pathlib import Path

import numpy as np

from tag_palette.shared.device import get_torch_device

logger = logging.getLogger(__name__)

_model = None
_tag_embeddings: dict[str, np.ndarray] = {}
_CACHE_FILE = "tag_embeddings.npy"


def _get_model():
    """Load the SentenceTransformer model lazily."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        device = get_torch_device()
        _model = SentenceTransformer(
            "paraphrase-MiniLM-L6-v2",
            device=device,
            local_files_only=True,
        )
        logger.info("SentenceTransformer model loaded (device=%s)", device)
    return _model


def _default_cache_path() -> Path:
    """Return the default tag embedding cache path."""
    import importlib.resources

    return Path(str(importlib.resources.files("tag_palette") / "data" / _CACHE_FILE))


def load_tag_embeddings(cache_path: Path | None = None) -> None:
    """Load cached tag embeddings from a .npy file."""
    path = cache_path or _default_cache_path()
    if not path.exists():
        return
    try:
        data = np.load(path, allow_pickle=True).item()
        _tag_embeddings.update(data)
        logger.info("Tag embedding cache loaded: %d entries", len(_tag_embeddings))
    except Exception as e:
        logger.warning("Failed to load tag embedding cache: %s", e)


def save_tag_embeddings(cache_path: Path | None = None) -> None:
    """Persist cached tag embeddings to a .npy file."""
    path = cache_path or _default_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, _tag_embeddings)
    logger.info("Tag embedding cache saved: %d entries", len(_tag_embeddings))


def _get_tag_embedding(tag_name: str) -> np.ndarray:
    """Resolve one tag into an embedding vector, using the cache when possible."""
    if tag_name not in _tag_embeddings:
        model = _get_model()
        readable = tag_name.replace("_", " ")
        vec = model.encode(readable, normalize_embeddings=True)
        _tag_embeddings[tag_name] = vec
    return _tag_embeddings[tag_name]


def tags_to_embedding(tags: dict[str, float]) -> bytes:
    """Convert weighted tags into one normalized embedding."""
    if not tags:
        return b""

    vectors = []
    weights = []
    for tag_name, confidence in tags.items():
        vec = _get_tag_embedding(tag_name)
        vectors.append(vec)
        weights.append(confidence)

    vectors_arr = np.array(vectors, dtype=np.float32)
    weights_arr = np.array(weights, dtype=np.float32).reshape(-1, 1)

    weighted = (vectors_arr * weights_arr).sum(axis=0)
    norm = np.linalg.norm(weighted)
    if norm > 0:
        weighted = weighted / norm

    return weighted.astype(np.float32).tobytes()


def embedding_to_base64(embedding_bytes: bytes) -> str:
    """Encode embedding bytes as base64 text."""
    return base64.b64encode(embedding_bytes).decode("ascii")


def base64_to_embedding(b64_str: str) -> np.ndarray:
    """Decode base64 text back into a float32 numpy vector."""
    raw = base64.b64decode(b64_str)
    return np.frombuffer(raw, dtype=np.float32)
