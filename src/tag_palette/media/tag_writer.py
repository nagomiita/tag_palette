"""画像タグの Eagle metadata.json / tag_palette.json への書き戻し。"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import numpy as np

from tag_palette import (
    tags_to_embedding,
    translate_tags,
)
from tag_palette.media.eagle_scanner import EagleImage, is_image_file
from tag_palette.media.genre import _get_genre_df
from tag_palette.media.sensitive import detect_sensitive
from tag_palette.shared.csv_reader import load_clean_tag_csv

logger = logging.getLogger(__name__)

_danbooru_df = None


def _get_danbooru_df():
    global _danbooru_df
    if _danbooru_df is None:
        _danbooru_df = load_clean_tag_csv(require_ja=False)
    return _danbooru_df


def detect_genre(tags: dict[str, float]) -> str | None:
    """タグ辞書から最も信頼度の高いタグのジャンルを返す。見つからなければ None。"""
    df = _get_danbooru_df()
    for tag_name in sorted(tags, key=tags.get, reverse=True):
        if tag_name in df.index:
            genre = str(df.loc[tag_name, "genre"]).strip()
            if genre:
                return genre
    return None


def get_genre_ja(genre_key: str) -> str:
    """genre.csv からジャンルの日本語名を取得する。見つからなければキーをそのまま返す。"""
    genre_df = _get_genre_df()
    if genre_key in genre_df.index:
        ja = str(genre_df.loc[genre_key, "ja"]).strip()
        if ja:
            return ja
    return genre_key


def write_tags_to_eagle(
    eagle_image: EagleImage,
    tags: dict[str, float],
    model_name: str,
    ratings: dict[str, float] | None = None,
) -> None:
    """タグの日本語訳を Eagle の metadata.json の annotation に書き込み、
    tag_palette.json にタグ生データを保存する。"""
    tag_names = list(tags.keys())
    ja_tags = translate_tags(tag_names)

    # ジャンル検出
    genre = detect_genre(tags)

    # Eagle metadata.json に annotation と tags 書き込み
    try:
        with open(eagle_image.metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        meta["annotation"] = ", ".join(ja_tags)

        # genre が見つかれば Eagle の tags に日本語名を追加
        if genre:
            eagle_tags: list[str] = meta.get("tags", [])
            genre_ja = get_genre_ja(genre)
            if genre_ja not in eagle_tags:
                eagle_tags.append(genre_ja)
                meta["tags"] = eagle_tags

        with open(eagle_image.metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except Exception as e:
        logger.error("metadata.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    # 埋め込みベクトル生成 → .npy 保存
    try:
        embedding_bytes = tags_to_embedding(tags)
        if embedding_bytes:
            embedding_arr = np.frombuffer(embedding_bytes, dtype=np.float32)
            npy_path = eagle_image.info_dir / "embedding.npy"
            np.save(npy_path, embedding_arr)
    except Exception as e:
        logger.error("埋め込み生成失敗: %s -> %s", eagle_image.eagle_id, e)

    # CCIP キャラクター特徴ベクトル生成 → .npy 保存
    if is_image_file(eagle_image):
        ccip_path = eagle_image.info_dir / "ccip_embedding.npy"
        if not ccip_path.exists():
            try:
                from imgutils.metrics import ccip_extract_feature

                target = eagle_image.thumbnail_path if eagle_image.thumbnail_path.exists() else eagle_image.image_path
                feat = ccip_extract_feature(str(target))
                np.save(ccip_path, feat.astype(np.float32))
            except Exception as e:
                logger.warning("CCIP 抽出失敗: %s -> %s", eagle_image.eagle_id, e)

    # ポーズ埋め込みベクトル生成 → .npy 保存
    if is_image_file(eagle_image):
        pose_path = eagle_image.info_dir / "pose_embedding.npy"
        if not pose_path.exists():
            try:
                from tag_palette.media.pose_embedding import extract_pose_embedding

                target = eagle_image.thumbnail_path if eagle_image.thumbnail_path.exists() else eagle_image.image_path
                pose_vec = extract_pose_embedding(str(target))
                if pose_vec is not None:
                    np.save(pose_path, pose_vec)
            except Exception as e:
                logger.warning("ポーズ抽出失敗: %s -> %s", eagle_image.eagle_id, e)

    # 画像分類スコア判定
    ai_score: float | None = None
    real_score: float | None = None
    monochrome_score: float | None = None
    classify_scores: dict[str, float] | None = None
    completeness_scores: dict[str, float] | None = None
    portrait_scores: dict[str, float] | None = None
    if is_image_file(eagle_image):
        target = eagle_image.thumbnail_path if eagle_image.thumbnail_path.exists() else eagle_image.image_path
        target_str = str(target)

        try:
            from imgutils.validate import get_ai_created_score
            ai_score = get_ai_created_score(target_str)
        except Exception as e:
            logger.warning("AI 判定失敗: %s -> %s", eagle_image.eagle_id, e)

        try:
            from imgutils.validate import anime_real_score
            scores = anime_real_score(target_str)
            real_score = scores.get("real")
        except Exception as e:
            logger.warning("実写判定失敗: %s -> %s", eagle_image.eagle_id, e)

        try:
            from imgutils.validate import get_monochrome_score
            monochrome_score = get_monochrome_score(target_str)
        except Exception as e:
            logger.warning("モノクロ判定失敗: %s -> %s", eagle_image.eagle_id, e)

        try:
            from imgutils.validate import anime_classify_score
            classify_scores = anime_classify_score(target_str)
        except Exception as e:
            logger.warning("分類判定失敗: %s -> %s", eagle_image.eagle_id, e)

        try:
            from imgutils.validate import anime_completeness_score
            completeness_scores = anime_completeness_score(target_str)
        except Exception as e:
            logger.warning("完成度判定失敗: %s -> %s", eagle_image.eagle_id, e)

        try:
            from imgutils.validate import anime_portrait_score
            portrait_scores = anime_portrait_score(target_str)
        except Exception as e:
            logger.warning("構図判定失敗: %s -> %s", eagle_image.eagle_id, e)

    # tag_palette.json にタグ生データ保存
    try:
        tp_path = eagle_image.info_dir / "tag_palette.json"

        # 統合センシティブ判定 (WD14 rating → anime_rating → タグ辞書)
        image_for_rating = None
        if is_image_file(eagle_image):
            target = eagle_image.thumbnail_path if eagle_image.thumbnail_path.exists() else eagle_image.image_path
            image_for_rating = str(target)

        sensitive_result = detect_sensitive(
            ratings=ratings,
            image=image_for_rating,
        )

        tp_data = {
            "id": eagle_image.eagle_id,
            "name": eagle_image.image_path.name,
            "thumbnail_name": eagle_image.thumbnail_path.name,
            "ext": eagle_image.ext,
            "genre": genre,
            "is_sensitive": sensitive_result["is_sensitive"],
            "sensitive_method": sensitive_result["method"],
            "wd14_ratings": sensitive_result["wd14_ratings"],
            "anime_rating": sensitive_result["anime_rating"],
            "ai_score": ai_score,
            "real_score": real_score,
            "monochrome_score": monochrome_score,
            "classify_scores": classify_scores,
            "completeness_scores": completeness_scores,
            "portrait_scores": portrait_scores,
            "model_name": model_name,
            "tags": tags,
            "tags_ja": dict(zip(tag_names, ja_tags)),
            "generated_at": datetime.now().isoformat(),
        }
        with open(tp_path, "w", encoding="utf-8") as f:
            json.dump(tp_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("tag_palette.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)
