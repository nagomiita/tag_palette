"""小説の解析・Eagle metadata.json / tag_palette.json への書き戻し。"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from tag_palette.media.eagle_scanner import EagleImage

logger = logging.getLogger(__name__)


def _parse_novel(eagle_image: EagleImage) -> dict:
    """小説ファイルを解析してメタデータを返す。"""
    ext = eagle_image.ext.lower()
    file_path = eagle_image.image_path

    if ext == "pdf":
        from tag_palette.novel.pdf_parser import parse_pdf
        novel = parse_pdf(file_path)
        return {
            "novel_id": novel.n_code,
            "title": novel.title,
            "author": novel.author,
            "url": novel.url,
            "tags": novel.tags,
            "body": novel.body,
            "is_sensitive": novel.is_sensitive,
        }

    # .txt (Pixiv / Fanbox format)
    text = file_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    url = lines[0].strip() if len(lines) > 0 else ""
    author = lines[2].strip() if len(lines) > 2 else ""
    title = eagle_image.name
    tag_line = lines[6].strip() if len(lines) > 6 else ""

    tags: list[str] = []
    if tag_line.startswith("Tags:"):
        tags = [t.strip() for t in tag_line[5:].split(",") if t.strip()]
        body = "\n".join(lines[8:])
    else:
        body = "\n".join(lines[6:])

    sensitive_tags = {"18禁", "R-18", "R18"}
    is_sensitive = any(t.strip() in sensitive_tags for t in tags)

    return {
        "novel_id": eagle_image.eagle_id,
        "title": title,
        "author": author,
        "url": url,
        "tags": tags,
        "body": body,
        "is_sensitive": is_sensitive,
    }


def write_novel_to_eagle(eagle_image: EagleImage) -> dict:
    """小説ファイルを解析し、tag_palette.json に保存する。

    Returns:
        解析結果の概要。
    """
    data = _parse_novel(eagle_image)

    # チャンク分割
    from tag_palette.novel.chunker import chunk_text
    chunks = chunk_text(data["body"])

    # 形態素解析
    from tag_palette.novel.morpheme import extract_morphemes
    morpheme_summary: dict[str, int] = {}
    for chunk in chunks:
        for (surface, _pos), count in extract_morphemes(chunk.body).items():
            morpheme_summary[surface] = morpheme_summary.get(surface, 0) + count

    # Eagle metadata.json に annotation 書き込み
    try:
        with open(eagle_image.metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        # タイトルと作者を annotation に
        annotation_parts = [data["title"]]
        if data["author"]:
            annotation_parts.append(data["author"])
        if data["tags"]:
            annotation_parts.append(", ".join(data["tags"][:5]))
        meta["annotation"] = " / ".join(annotation_parts)

        # タグを Eagle tags に追加
        eagle_tags: list[str] = meta.get("tags", [])
        for tag in data["tags"]:
            if tag not in eagle_tags:
                eagle_tags.append(tag)
        if "小説" not in eagle_tags:
            eagle_tags.append("小説")
        meta["tags"] = eagle_tags

        with open(eagle_image.metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except Exception as e:
        logger.error("metadata.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    # tag_palette.json に保存
    try:
        tp_path = eagle_image.info_dir / "tag_palette.json"
        tp_data = {
            "id": data["novel_id"],
            "media_type": "novel",
            "title": data["title"],
            "author": data["author"],
            "url": data["url"],
            "tags": data["tags"],
            "is_sensitive": data["is_sensitive"],
            "num_chunks": len(chunks),
            "num_morphemes": len(morpheme_summary),
            "chunks": [
                {"seq": c.seq, "kind": c.kind, "body": c.body}
                for c in chunks
            ],
            "morphemes": morpheme_summary,
            "generated_at": datetime.now().isoformat(),
        }
        with open(tp_path, "w", encoding="utf-8") as f:
            json.dump(tp_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("tag_palette.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    return {
        "title": data["title"],
        "author": data["author"],
        "num_chunks": len(chunks),
        "num_morphemes": len(morpheme_summary),
        "num_tags": len(data["tags"]),
    }
