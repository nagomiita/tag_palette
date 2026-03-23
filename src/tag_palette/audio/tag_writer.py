"""音声タグの Eagle metadata.json / tag_palette.json への書き戻し。"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from tag_palette.media.eagle_scanner import EagleImage

logger = logging.getLogger(__name__)


def write_audio_tags_to_eagle(
    eagle_image: EagleImage,
    result,
) -> None:
    """音声タグ結果を Eagle の metadata.json と tag_palette.json に保存する。"""
    from tag_palette.audio.labels_ja import get_japanese_description

    # 日本語説明を生成
    desc_ja = get_japanese_description(
        result.tags, result.audio_type.value, result.transcript,
    )

    # Eagle metadata.json に annotation 書き込み
    try:
        with open(eagle_image.metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        meta["annotation"] = desc_ja

        # audio_type を Eagle の tags に追加
        eagle_tags: list[str] = meta.get("tags", [])
        type_label = result.audio_type.value.upper()
        if type_label not in eagle_tags:
            eagle_tags.append(type_label)
            meta["tags"] = eagle_tags

        with open(eagle_image.metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except Exception as e:
        logger.error("metadata.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    # tag_palette.json に保存 (audio_assets テーブルに対応)
    try:
        tp_path = eagle_image.info_dir / "tag_palette.json"
        file_size = eagle_image.image_path.stat().st_size if eagle_image.image_path.exists() else None
        tp_data = {
            "id": eagle_image.eagle_id,
            "file_path": str(eagle_image.image_path),
            "file_name": eagle_image.image_path.name,
            "file_extension": eagle_image.ext,
            "media_type": "audio",
            "audio_type": result.audio_type.value,
            "duration_ms": result.duration_ms,
            "sample_rate": result.sample_rate,
            "file_size": file_size,
            "description": desc_ja,
            "transcript": result.transcript,
            "model_name": result.model_name,
            "tags": result.tags,
            "generated_at": datetime.now().isoformat(),
        }
        with open(tp_path, "w", encoding="utf-8") as f:
            json.dump(tp_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("tag_palette.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)
