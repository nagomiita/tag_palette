"""画像タグ生成モジュール (imgutils.tagging ベース)。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class TagResult:
    """タグ生成結果を格納するデータクラス。

    Attributes:
        model_name: 使用したモデル名
        tags: タグ名と信頼度のマッピング
        ratings: WD14 rating カテゴリと信頼度 (general, sensitive, questionable, explicit)
    """

    model_name: str
    tags: dict[str, float]
    ratings: dict[str, float] | None = None


# ── imgutils モデル名 → 旧モデル名 互換マッピング ─────────────

# imgutils の get_wd14_tags で使えるモデル名
WD14_MODELS: dict[str, str] = {
    # 旧名 → imgutils モデル名
    "wd-eva02-large-tagger-v3": "EVA02_Large",
    "wd-vit-large-tagger-v3": "ViT_Large",
    "wd-v1-4-swinv2-tagger.v3": "SwinV2_v3",
    "wd-v1-4-convnext-tagger.v3": "ConvNext_v3",
    "wd-v1-4-vit-tagger.v3": "ViT_v3",
    "wd14-swinv2-v1": "SwinV2",
    "wd14-convnext.v2": "ConvNext",
    "wd14-convnextv2.v1": "ConvNextV2",
    "wd14-vit.v2": "ViT",
    "wd-v1-4-moat-tagger.v2": "MOAT",
    # imgutils ネイティブ名もそのまま使える
    "EVA02_Large": "EVA02_Large",
    "ViT_Large": "ViT_Large",
    "SwinV2_v3": "SwinV2_v3",
    "ConvNext_v3": "ConvNext_v3",
    "ViT_v3": "ViT_v3",
    "SwinV2": "SwinV2",
    "ConvNext": "ConvNext",
    "ConvNextV2": "ConvNextV2",
    "ViT": "ViT",
    "MOAT": "MOAT",
}

# imgutils の他タガー
CAMIE_MODELS = {"camie-tagger", "camie-tagger-v2"}
MLDANBOORU_MODELS = {"mld-caformer.dec-5-97527", "mld-tresnetd.6-30000", "mldanbooru"}
PIXAI_MODELS = {"pixai-tagger-v0.9", "pixai"}

ALL_MODELS = set(WD14_MODELS.keys()) | CAMIE_MODELS | MLDANBOORU_MODELS | PIXAI_MODELS


def _interrogate(image_path: Path, model_name: str) -> TagResult:
    """imgutils を使って1画像をタグ付けする。"""
    image_str = str(image_path)

    if model_name in WD14_MODELS:
        from imgutils.tagging import get_wd14_tags
        imgutils_name = WD14_MODELS[model_name]
        rating, general, character = get_wd14_tags(
            image_str,
            model_name=imgutils_name,
            general_threshold=0.35,
            character_threshold=0.85,
            no_underline=False,
            drop_overlap=True,
            fmt=("rating", "general", "character"),
        )
        tags = {**general, **character}
        return TagResult(model_name=model_name, tags=tags, ratings=rating or None)

    if model_name in CAMIE_MODELS:
        from imgutils.tagging import get_camie_tags
        camie_model = "initial" if model_name == "camie-tagger" else "v2"
        rating, general, character = get_camie_tags(
            image_str,
            model_name=camie_model,
            no_underline=False,
            drop_overlap=True,
            fmt=("rating", "general", "character"),
        )
        tags = {**general, **character}
        return TagResult(model_name=model_name, tags=tags, ratings=rating or None)

    if model_name in MLDANBOORU_MODELS:
        from imgutils.tagging import get_mldanbooru_tags
        tags = get_mldanbooru_tags(
            image_str,
            use_real_name=False,
            threshold=0.7,
            drop_overlap=True,
        )
        return TagResult(model_name=model_name, tags=tags, ratings=None)

    if model_name in PIXAI_MODELS:
        from imgutils.tagging import get_pixai_tags
        general, character = get_pixai_tags(
            image_str,
            fmt=("general", "character"),
        )
        tags = {**general, **character}
        return TagResult(model_name=model_name, tags=tags, ratings=None)

    raise ValueError(f"Unknown model: {model_name}. Available: {sorted(ALL_MODELS)}")


def generate_tags(
    image_path: str | Path,
    model_name: str = "wd-eva02-large-tagger-v3",
    use_all_models: bool = False,
) -> list[TagResult]:
    """画像からタグを生成する。

    Parameters:
        image_path: 画像ファイルのパス
        model_name: 使用するモデル名 (デフォルト: wd-eva02-large-tagger-v3)
        use_all_models: True の場合、WD14 の全モデルで推論する

    Returns:
        TagResult のリスト。各要素にモデル名とタグ(信頼度付き)を含む。
    """
    image_path = Path(image_path)
    results = []

    if use_all_models:
        model_list = list(WD14_MODELS.keys())
    else:
        model_list = [model_name]

    for name in model_list:
        try:
            result = _interrogate(image_path, name)
            if result.tags:
                results.append(result)
        except Exception as e:
            logger.warning("Skipped model '%s' due to error: %s", name, e)

    return results


def generate_tags_batch(
    image_paths: list[str | Path],
    model_name: str = "wd-eva02-large-tagger-v3",
    batch_size: int = 4,
    max_workers: int = 4,  # noqa: ARG001 - 互換性のため残す
    on_batch_done: Callable[[int, int], None] | None = None,
) -> list[TagResult]:
    """複数画像を逐次処理でタグ生成する。

    Parameters:
        image_paths: 画像ファイルパスのリスト
        model_name: 使用するモデル名
        batch_size: コールバック通知の単位
        max_workers: (未使用、互換性のため残す)
        on_batch_done: バッチ完了時のコールバック (処理済み数, 全体数)

    Returns:
        TagResult のリスト（入力と同じ順序）。処理失敗した画像は tags が空。
    """
    paths = [Path(p) for p in image_paths]
    total = len(paths)
    results: list[TagResult] = []

    for i, path in enumerate(paths):
        try:
            result = _interrogate(path, model_name)
            results.append(result)
        except Exception as e:
            logger.warning("Skipped image due to error: %s", e)
            results.append(TagResult(model_name=model_name, tags={}))

        if on_batch_done and (i + 1) % batch_size == 0:
            on_batch_done(i + 1, total)

    if on_batch_done and total % batch_size != 0:
        on_batch_done(total, total)

    return results
