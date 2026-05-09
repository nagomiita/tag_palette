"""小説の解析・Eagle metadata.json / tag_palette.json への書き戻し。"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from tag_palette.media.eagle_scanner import EagleImage

logger = logging.getLogger(__name__)

# title 内の全角数字のみ半角化する変換テーブル。Pixiv などで「その８」
# のように本文内に紛れ込む全角数字を統一表記にしたいが、全角アルファベット
# は人名等で意味があるケースもあるので変換対象外。
_FULLWIDTH_DIGITS_TO_HALFWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")


def _parse_novel(eagle_image: EagleImage) -> dict:
    """小説ファイルを解析してメタデータを返す。"""
    ext = eagle_image.ext.lower()
    file_path = eagle_image.image_path

    if ext == "pdf":
        from tag_palette.novel.pdf_parser import parse_pdf_as_series
        series = parse_pdf_as_series(file_path)
        chapters = series.chapters
        if chapters:
            body = "\n".join(ch.body for ch in chapters)
            chapter_info = [
                {"seq": ch.seq, "title": ch.title}
                for ch in chapters
            ]
        else:
            body = ""
            chapter_info = []
        return {
            "novel_id": series.n_code,
            "title": series.title,
            "author": series.author,
            "description": series.description,
            "url": series.url,
            "tags": [],
            "body": body,
            "is_sensitive": series.is_sensitive,
            "chapters": chapter_info,
            "_series_chapters": chapters,
        }

    # .txt (Pixiv / Fanbox format)
    text = file_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    url = lines[0].strip() if len(lines) > 0 else ""
    author = lines[2].strip() if len(lines) > 2 else ""
    # Pixiv files are named `{pixiv_id}_{title}.txt`; strip the numeric ID
    # prefix so the title doesn't end up as e.g. "10007098_…". Non-Pixiv
    # files (no leading digits) keep the full stem.
    # title 中の全角数字 (例: "その８") は半角に正規化する。
    name = eagle_image.name
    head, sep, tail = name.partition("_")
    raw_title = tail if sep and head.isdigit() and tail else name
    title = raw_title.translate(_FULLWIDTH_DIGITS_TO_HALFWIDTH)
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

    # 章ごとにチャンク分割・形態素解析
    from tag_palette.novel.chunker import chunk_text
    from tag_palette.novel.morpheme import extract_morphemes

    series_chapters = data.pop("_series_chapters", None)
    chapter_info: list[dict] = data.get("chapters", [])

    all_chunks: list[dict] = []
    morpheme_summary: dict[str, int] = {}

    if series_chapters and chapter_info:
        # 章ごとに処理し、各チャンクに chapter_seq を付与
        global_seq = 0
        for ch in series_chapters:
            ch_chunks = chunk_text(ch.body)
            for c in ch_chunks:
                all_chunks.append({
                    "seq": global_seq,
                    "kind": c.kind,
                    "body": c.body,
                    "chapter_seq": ch.seq,
                })
                for (surface, _pos), count in extract_morphemes(c.body).items():
                    morpheme_summary[surface] = morpheme_summary.get(surface, 0) + count
                global_seq += 1
    else:
        # 章なし (txt ファイル等)
        chunks = chunk_text(data["body"])
        for c in chunks:
            all_chunks.append({"seq": c.seq, "kind": c.kind, "body": c.body})
            for (surface, _pos), count in extract_morphemes(c.body).items():
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
        tp_data: dict = {
            "id": data["novel_id"],
            "media_type": "novel",
            "title": data["title"],
            "author": data["author"],
            "description": data.get("description", ""),
            "url": data["url"],
            "tags": data["tags"],
            "is_sensitive": data["is_sensitive"],
            "num_chunks": len(all_chunks),
            "num_morphemes": len(morpheme_summary),
            "chunks": all_chunks,
            "morphemes": morpheme_summary,
            "generated_at": datetime.now().isoformat(),
        }
        if chapter_info:
            tp_data["chapters"] = chapter_info
        with open(tp_path, "w", encoding="utf-8") as f:
            json.dump(tp_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("tag_palette.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    return {
        "title": data["title"],
        "author": data["author"],
        "num_chunks": len(all_chunks),
        "num_morphemes": len(morpheme_summary),
        "num_tags": len(data["tags"]),
        "num_chapters": len(chapter_info),
    }
