"""tag_palette.json の読み込み。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np

from .models import AudioPaletteEntry, NovelPaletteEntry, TagPaletteEntry

logger = logging.getLogger(__name__)

LAST_IMPORT_FILE = "last_import.txt"


def _last_import_path(image_dir: Path) -> Path:
    return image_dir.parent / LAST_IMPORT_FILE


def load_last_import(image_dir: Path) -> datetime | None:
    path = _last_import_path(image_dir)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return datetime.fromisoformat(text)
    except (ValueError, OSError):
        return None


def save_last_import(image_dir: Path, run_time: datetime) -> None:
    path = _last_import_path(image_dir)
    path.write_text(run_time.isoformat(), encoding="utf-8")


def load_tag_palettes(
    image_dir: Path,
    *,
    since: datetime | None = None,
    since_generated: datetime | None = None,
) -> tuple[list[TagPaletteEntry], list[AudioPaletteEntry], list[NovelPaletteEntry]]:
    """images ディレクトリから tag_palette.json を読み込む。

    Returns:
        (media_entries, audio_entries, novel_entries) のタプル。
    """
    cutoff = since.timestamp() if since else 0
    entries: list[TagPaletteEntry] = []
    audio_entries: list[AudioPaletteEntry] = []
    novel_entries: list[NovelPaletteEntry] = []

    scanned = 0
    skipped = 0
    for info_dir in sorted(image_dir.iterdir()):
        if not info_dir.is_dir() or not info_dir.name.endswith(".info"):
            continue

        scanned += 1
        if scanned % 5000 == 0:
            logger.info(
                "スキャン中... %d ディレクトリ (media: %d, audio: %d, novel: %d, スキップ: %d)",
                scanned, len(entries), len(audio_entries), len(novel_entries), skipped,
            )

        tp_path = info_dir / "tag_palette.json"
        if not tp_path.exists():
            continue

        if cutoff and tp_path.stat().st_mtime < cutoff:
            skipped += 1
            continue

        try:
            with open(tp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("読み込み失敗: %s -> %s", tp_path, e)
            continue

        # generated_at フィルタ (st_mtime より正確)
        gen_at = data.get("generated_at", "")
        if since and gen_at:
            try:
                if gen_at < since.isoformat():
                    skipped += 1
                    continue
            except (TypeError, ValueError):
                pass
        if since_generated and gen_at:
            try:
                if gen_at < since_generated.isoformat():
                    skipped += 1
                    continue
            except (TypeError, ValueError):
                pass

        media_type = data.get("media_type", "")

        # ── 音声エントリ ──
        if media_type == "audio":
            asset_id = data.get("id", info_dir.name.replace(".info", ""))
            audio_entries.append(
                AudioPaletteEntry(
                    asset_id=asset_id,
                    file_path=data.get("file_path", ""),
                    file_name=data.get("file_name", ""),
                    file_extension=data.get("file_extension", ""),
                    audio_type=data.get("audio_type", "bgm"),
                    duration_ms=data.get("duration_ms"),
                    sample_rate=data.get("sample_rate"),
                    file_size=data.get("file_size"),
                    description=data.get("description"),
                    transcript=data.get("transcript"),
                    model_name=data.get("model_name", ""),
                    tags=data.get("tags", {}),
                    generated_at=data.get("generated_at", ""),
                )
            )
            continue

        # ── 小説エントリ ──
        if media_type == "novel":
            novel_id = data.get("id", info_dir.name.replace(".info", ""))
            raw_tags = data.get("tags", [])
            novel_entries.append(
                NovelPaletteEntry(
                    novel_id=novel_id,
                    title=data.get("title", ""),
                    author=data.get("author", ""),
                    url=data.get("url", ""),
                    tags=raw_tags if isinstance(raw_tags, list) else [],
                    is_sensitive=bool(data.get("is_sensitive", False)),
                    num_chunks=data.get("num_chunks", 0),
                    num_morphemes=data.get("num_morphemes", 0),
                    chunks=data.get("chunks", []),
                    generated_at=data.get("generated_at", ""),
                )
            )
            continue

        # ── メディアエントリ (画像/動画/HTML) ──
        image_id = data.get("image_id") or data.get(
            "id", info_dir.name.replace(".info", "")
        )

        # embedding.npy を読み込み
        tag_embedding: bytes | None = None
        emb_path = info_dir / "embedding.npy"
        if emb_path.exists():
            try:
                arr = np.load(emb_path)
                tag_embedding = arr.astype(np.float32).tobytes()
            except Exception as e:
                logger.warning("embedding.npy 読み込み失敗: %s -> %s", emb_path, e)

        # ccip_embedding.npy を読み込み
        ccip_embedding: bytes | None = None
        ccip_path = info_dir / "ccip_embedding.npy"
        if ccip_path.exists():
            try:
                arr = np.load(ccip_path)
                ccip_embedding = arr.astype(np.float32).tobytes()
            except Exception as e:
                logger.warning("ccip_embedding.npy 読み込み失敗: %s -> %s", ccip_path, e)

        # pose_embedding.npy を読み込み
        pose_embedding: bytes | None = None
        pose_path = info_dir / "pose_embedding.npy"
        if pose_path.exists():
            try:
                arr = np.load(pose_path)
                pose_embedding = arr.astype(np.float32).tobytes()
            except Exception as e:
                logger.warning("pose_embedding.npy 読み込み失敗: %s -> %s", pose_path, e)

        entries.append(
            TagPaletteEntry(
                image_id=image_id,
                image_name=data.get("image_name") or data.get("name", ""),
                thumbnail_name=data.get("thumbnail_name", ""),
                ext=data.get("ext", ""),
                model_name=data.get("model_name", ""),
                genre=data.get("genre"),
                is_sensitive=bool(data.get("is_sensitive", False)),
                ai_score=data.get("ai_score"),
                real_score=data.get("real_score"),
                monochrome_score=data.get("monochrome_score"),
                classify_scores=data.get("classify_scores"),
                completeness_scores=data.get("completeness_scores"),
                portrait_scores=data.get("portrait_scores"),
                tags=data.get("tags", {}),
                tags_ja=data.get("tags_ja", {}),
                generated_at=data.get("generated_at", ""),
                info_dir=info_dir,
                tag_embedding=tag_embedding,
                ccip_embedding=ccip_embedding,
                pose_embedding=pose_embedding,
                ocr_text=data.get("ocr_full_text"),
            )
        )

    html_count = sum(1 for e in entries if e.ext.lower().strip(".") in ("html", "htm"))
    image_count = len(entries) - html_count
    logger.info(
        "スキャン完了: %d ディレクトリ (image: %d, html: %d, novel: %d, audio: %d, スキップ: %d)",
        scanned, image_count, html_count, len(novel_entries), len(audio_entries), skipped,
    )
    return entries, audio_entries, novel_entries
