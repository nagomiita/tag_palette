from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage

logger = logging.getLogger(__name__)


# ── WD14 rating ベースの判定 ────────────────────────────


def is_sensitive_by_ratings(
    ratings: dict[str, float] | None,
    threshold: float = 0.5,
) -> bool | None:
    """WD14 tagger の rating 出力からセンシティブ判定する。

    ratings は {"general": 0.1, "sensitive": 0.3, "questionable": 0.4, "explicit": 0.2}
    のような辞書。questionable + explicit の合計が threshold 以上なら True。

    Returns:
        True/False、ratings が空なら None（判定不能）。
    """
    if not ratings:
        return None
    nsfw_score = ratings.get("questionable", 0.0) + ratings.get("explicit", 0.0)
    return nsfw_score >= threshold


# ── imgutils anime_rating ベースの判定 ──────────────────


def get_anime_rating(
    image: str | Path | PILImage.Image,
    model_name: str = "mobilenetv3_v1_pruned_ls0.1",
) -> dict[str, float]:
    """imgutils の anime_rating_score で画像のレーティングスコアを取得する。

    Returns:
        {"safe": 0.99, "r15": 0.005, "r18": 0.002} のような辞書。
        エラー時は空辞書。
    """
    try:
        from imgutils.validate import anime_rating_score
        return anime_rating_score(image, model_name=model_name)
    except Exception as e:
        logger.warning("anime_rating 判定失敗: %s", e)
        return {}


def is_sensitive_by_anime_rating(
    image: str | Path | PILImage.Image,
    model_name: str = "mobilenetv3_v1_pruned_ls0.1",
    threshold: float = 0.5,
) -> bool | None:
    """imgutils anime_rating で画像がセンシティブか判定する。

    r15 + r18 の合計が threshold 以上なら True。

    Returns:
        True/False、判定失敗時は None。
    """
    scores = get_anime_rating(image, model_name=model_name)
    if not scores:
        return None
    nsfw_score = scores.get("r15", 0.0) + scores.get("r18", 0.0)
    return nsfw_score >= threshold


# ── 統合判定 ────────────────────────────────────────────


def detect_sensitive(
    ratings: dict[str, float] | None = None,
    image: str | Path | PILImage.Image | None = None,
    rating_threshold: float = 0.5,
    anime_rating_threshold: float = 0.5,
    anime_rating_model: str = "mobilenetv3_v1_pruned_ls0.1",
) -> dict:
    """WD14 rating と anime_rating を組み合わせてセンシティブ判定を行う。

    判定優先順位:
      1. WD14 rating (タグ生成時に無料で取得済み)
      2. imgutils anime_rating (画像が渡された場合)

    Returns:
        {
            "is_sensitive": bool,
            "method": str,           # 判定に使用した手法
            "wd14_ratings": dict,    # WD14 rating 生スコア
            "anime_rating": dict,    # anime_rating 生スコア (画像指定時)
        }
    """
    result = {
        "is_sensitive": False,
        "method": "none",
        "wd14_ratings": ratings or {},
        "anime_rating": {},
    }

    # 1. WD14 rating
    wd14_result = is_sensitive_by_ratings(ratings, threshold=rating_threshold)
    if wd14_result is not None:
        result["is_sensitive"] = wd14_result
        result["method"] = "wd14_rating"
        return result

    # 2. imgutils anime_rating
    if image is not None:
        scores = get_anime_rating(image, model_name=anime_rating_model)
        result["anime_rating"] = scores
        if scores:
            nsfw_score = scores.get("r15", 0.0) + scores.get("r18", 0.0)
            result["is_sensitive"] = nsfw_score >= anime_rating_threshold
            result["method"] = "anime_rating"
            return result

    return result
