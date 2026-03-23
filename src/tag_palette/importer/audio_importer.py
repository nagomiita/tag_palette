"""音声エントリの DB 書き込み。"""

from __future__ import annotations

import logging
import sqlite3

from .models import AudioPaletteEntry
from .utils import BATCH_SIZE, _chunked, _now_iso

logger = logging.getLogger(__name__)


def import_audio_entries(
    conn: sqlite3.Connection,
    entries: list[AudioPaletteEntry],
) -> dict[str, int]:
    """音声エントリを audio_assets テーブルに書き込む。"""
    now = _now_iso()
    stats = {"audio_created": 0, "audio_updated": 0}

    # 既存 audio_assets を file_path で一括取得
    existing_audio: set[str] = set()
    all_paths = [e.file_path for e in entries]
    for batch in _chunked(all_paths, BATCH_SIZE):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"SELECT file_path FROM audio_assets WHERE file_path IN ({placeholders})", batch
        ).fetchall()
        existing_audio.update(r[0] for r in rows)

    for i, entry in enumerate(entries):
        if entry.file_path in existing_audio:
            # UPDATE: audio_type, duration, sample_rate, description
            conn.execute(
                "UPDATE audio_assets SET audio_type = ?, duration_ms = ?, sample_rate = ?, "
                "description = ?, file_size = ? WHERE file_path = ?",
                (entry.audio_type.upper(), entry.duration_ms, entry.sample_rate,
                 entry.description, entry.file_size, entry.file_path),
            )
            stats["audio_updated"] += 1
        else:
            conn.execute(
                "INSERT INTO audio_assets (id, file_path, file_name, file_extension, "
                "audio_type, duration_ms, sample_rate, description, file_size, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.asset_id, entry.file_path, entry.file_name, entry.file_extension,
                 entry.audio_type.upper(), entry.duration_ms, entry.sample_rate,
                 entry.description, entry.file_size, now),
            )
            existing_audio.add(entry.file_path)
            stats["audio_created"] += 1

        if (i + 1) % 1000 == 0:
            conn.commit()
            logger.info("音声インポート: %d / %d 件", i + 1, len(entries))

    conn.commit()
    return stats
