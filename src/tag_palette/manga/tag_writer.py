"""漫画ページの解析結果を Eagle metadata.json / tag_palette.json に書き戻す。"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from tag_palette.media.eagle_scanner import EagleImage

logger = logging.getLogger(__name__)


def write_manga_to_eagle(
    eagle_image: EagleImage,
    *,
    model_name: str = "EVA02_Large",
) -> dict:
    """漫画ページを解析し、tag_palette.json に保存する。

    1. OpenCV でパネル検出 + NDLOCR-Lite でセリフ OCR
    2. ページ全体を WD14 でタグ付け

    Returns:
        解析結果の概要 dict。
    """
    from tag_palette.manga.analyzer import analyze_manga_page
    from tag_palette import generate_tags, translate_tags
    from tag_palette.tagger import TagResult

    image_path = eagle_image.image_path

    # 1. パネル検出 + NDLOCR-Lite で解析
    logger.info("  漫画解析中...")
    page_result = analyze_manga_page(image_path, do_ocr=True)

    # 2. ページ全体を WD14 でタグ付け
    page_tag_result: TagResult | None = None
    try:
        results = generate_tags(image_path, model_name=model_name)
        if results:
            page_tag_result = results[0]
    except Exception as e:
        logger.warning("  ページ全体タグ付け失敗: %s", e)

    # 翻訳
    page_tags = page_tag_result.tags if page_tag_result else {}
    tags_ja_map: dict[str, str] = {}
    if page_tags:
        try:
            names = list(page_tags.keys())
            ja_list = translate_tags(names)
            tags_ja_map = dict(zip(names, ja_list))
        except Exception as e:
            logger.warning("  タグ翻訳失敗: %s", e)

    # Eagle metadata.json に annotation 書き込み
    try:
        with open(eagle_image.metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        annotation_parts = []
        if page_result.ocr_full_text:
            preview = page_result.ocr_full_text[:100]
            if len(page_result.ocr_full_text) > 100:
                preview += "..."
            annotation_parts.append(preview)

        if page_tags:
            top_tags = list(page_tags.keys())[:5]
            top_ja = [tags_ja_map.get(t, t) for t in top_tags]
            annotation_parts.append(", ".join(top_ja))

        meta["annotation"] = " | ".join(annotation_parts)

        eagle_tags: list[str] = meta.get("tags", [])
        if "漫画" not in eagle_tags:
            eagle_tags.append("漫画")
        meta["tags"] = eagle_tags

        with open(eagle_image.metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except Exception as e:
        logger.error("metadata.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    # tag_palette.json に保存
    try:
        tp_path = eagle_image.info_dir / "tag_palette.json"

        page_ratings = page_tag_result.ratings if page_tag_result else None
        page_model = page_tag_result.model_name if page_tag_result else model_name

        is_sensitive = False
        if page_ratings:
            q_score = page_ratings.get("questionable", 0)
            e_score = page_ratings.get("explicit", 0)
            is_sensitive = (q_score + e_score) > 0.5

        tp_data = {
            "id": eagle_image.eagle_id,
            "media_type": "manga",
            "name": eagle_image.image_path.name,
            "thumbnail_name": eagle_image.thumbnail_path.name,
            "ext": eagle_image.ext,
            "is_sensitive": is_sensitive,
            "model_name": page_model,
            "tags": page_tags,
            "tags_ja": {k: tags_ja_map.get(k, k) for k in page_tags},
            "ratings": page_ratings,
            "num_panels": len(page_result.panels),
            "panels": [{"bbox": list(p.bbox)} for p in page_result.panels],
            "texts": [
                {"bbox": list(t.bbox), "text": t.text}
                for t in page_result.texts
            ],
            "ocr_full_text": page_result.ocr_full_text,
            "num_texts": len(page_result.texts),
            "generated_at": datetime.now().isoformat(),
        }
        with open(tp_path, "w", encoding="utf-8") as f:
            json.dump(tp_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("tag_palette.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    return {
        "num_panels": len(page_result.panels),
        "num_texts": len(page_result.texts),
        "ocr_preview": page_result.ocr_full_text[:50] if page_result.ocr_full_text else "",
        "num_page_tags": len(page_tags),
    }
