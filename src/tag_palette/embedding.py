from __future__ import annotations

import base64
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_model = None
_tag_embeddings: dict[str, np.ndarray] = {}
_CACHE_FILE = "tag_embeddings.npy"


def _get_model():
    """SentenceTransformer モデルを遅延ロードする。"""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("paraphrase-MiniLM-L6-v2", device="cpu")
        logger.info("SentenceTransformer モデルをロードしました (CPU)")
    return _model


def _default_cache_path() -> Path:
    """デフォルトのキャッシュファイルパスを返す (danbooru_tags.csv と同じディレクトリ)。"""
    import importlib.resources

    return Path(
        str(importlib.resources.files("tag_palette") / "data" / _CACHE_FILE)
    )


def load_tag_embeddings(cache_path: Path | None = None) -> None:
    """タグ埋め込みキャッシュを .npy から読み込む。"""
    path = cache_path or _default_cache_path()
    if not path.exists():
        return
    try:
        data = np.load(path, allow_pickle=True).item()
        _tag_embeddings.update(data)
        logger.info("タグ埋め込みキャッシュ読み込み: %d 件", len(_tag_embeddings))
    except Exception as e:
        logger.warning("タグ埋め込みキャッシュ読み込み失敗: %s", e)


def save_tag_embeddings(cache_path: Path | None = None) -> None:
    """タグ埋め込みキャッシュを .npy に保存する。"""
    path = cache_path or _default_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, _tag_embeddings)
    logger.info("タグ埋め込みキャッシュ保存: %d 件", len(_tag_embeddings))


def _get_tag_embedding(tag_name: str) -> np.ndarray:
    """タグ名の埋め込みベクトルを取得する (キャッシュあり)。"""
    if tag_name not in _tag_embeddings:
        model = _get_model()
        readable = tag_name.replace("_", " ")
        vec = model.encode(readable, normalize_embeddings=True)
        _tag_embeddings[tag_name] = vec
    return _tag_embeddings[tag_name]


def tags_to_embedding(tags: dict[str, float]) -> bytes:
    """タグ辞書 (名前→信頼度) から重み付き平均埋め込みを生成する。

    Parameters:
        tags: タグ名と信頼度のマッピング

    Returns:
        正規化された埋め込みベクトルの bytes (float32)
    """
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

    # 重み付き平均
    weighted = (vectors_arr * weights_arr).sum(axis=0)
    norm = np.linalg.norm(weighted)
    if norm > 0:
        weighted = weighted / norm

    return weighted.astype(np.float32).tobytes()


def embedding_to_base64(embedding_bytes: bytes) -> str:
    """埋め込み bytes を base64 文字列に変換する。"""
    return base64.b64encode(embedding_bytes).decode("ascii")


def base64_to_embedding(b64_str: str) -> np.ndarray:
    """base64 文字列を numpy 配列に復元する。"""
    raw = base64.b64decode(b64_str)
    return np.frombuffer(raw, dtype=np.float32)
