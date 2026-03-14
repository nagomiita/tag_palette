"""
media.desc_text を embedding 化して media_embeddings.desc_embedding に保存する。

小説チャンクと同じ intfloat/multilingual-e5-small モデルを使用。

Usage:
    uv run python embed_desc_text.py [--db PATH] [--batch-size N] [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

DB_DEFAULT = Path(r"C:\Users\taket\my_project\eagle\backend\local.db")
MODEL_NAME = "intfloat/multilingual-e5-small"


def get_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


def fetch_pending(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """desc_embedding が NULL で desc_text がある media を返す。"""
    rows = conn.execute(
        """
        SELECT m.id, m.desc_text
        FROM media m
        JOIN media_embeddings me ON me.media_id = m.id
        WHERE me.desc_embedding IS NULL
          AND m.desc_text IS NOT NULL
          AND m.desc_text != ''
        ORDER BY m.id
        """
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="desc_text → desc_embedding 一括生成"
    )
    parser.add_argument("--db", type=Path, default=DB_DEFAULT, help="SQLite DB パス")
    parser.add_argument("--batch-size", type=int, default=5000, help="一度にエンコードする件数")
    parser.add_argument("--dry-run", action="store_true", help="DB を更新せず件数のみ表示")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"DB が見つかりません: {args.db}")

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA journal_mode=WAL")

    pending = fetch_pending(conn)
    total = len(pending)
    print(f"対象: {total} 件")

    if total == 0 or args.dry_run:
        return

    print(f"モデル読み込み中: {MODEL_NAME}")
    model = get_model()

    embedded = 0
    start = time.perf_counter()

    for batch_start in range(0, total, args.batch_size):
        batch = pending[batch_start : batch_start + args.batch_size]
        media_ids = [mid for mid, _ in batch]
        texts = [text for _, text in batch]

        embeddings = model.encode(
            texts, normalize_embeddings=True, show_progress_bar=True
        )

        for mid, emb in zip(media_ids, embeddings):
            blob = emb.astype(np.float32).tobytes()
            conn.execute(
                "UPDATE media_embeddings SET desc_embedding = ? WHERE media_id = ?",
                (blob, mid),
            )
        conn.commit()

        embedded += len(batch)
        elapsed = time.perf_counter() - start
        speed = embedded / elapsed
        remaining = (total - embedded) / speed if speed > 0 else 0
        print(
            f"  {embedded}/{total} "
            f"({elapsed:.0f}s 経過, {speed:.0f} 件/s, "
            f"残り約 {remaining:.0f}s)"
        )

    elapsed = time.perf_counter() - start
    print(f"完了: {embedded} 件, {elapsed:.1f}s")
    conn.close()


if __name__ == "__main__":
    main()
