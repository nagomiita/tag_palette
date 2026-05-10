"""Ollama を使ってタグから自然言語の説明文を生成し、media.desc_text に保存する。

Usage:
    uv run python generate_descriptions.py
    uv run python generate_descriptions.py --model gemma3:12b --force
    uv run python generate_descriptions.py --host http://gpu-server:11434
    uv run python generate_descriptions.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    from tag_palette.shared.env_config import get_db_path
    from tag_palette.importer.desc_backfill import (
        OLLAMA_DEFAULT_HOST,
        OLLAMA_DEFAULT_MODEL,
        backfill_desc_text_ollama,
        recompute_desc_embedding,
    )

    parser = argparse.ArgumentParser(
        description="Ollama でタグから説明文を生成し desc_text に保存"
    )
    parser.add_argument(
        "--db-path", type=Path, default=get_db_path(),
        help="SQLite DB パス (env: SQLITE_DB_PATH)",
    )
    parser.add_argument(
        "--host", default=OLLAMA_DEFAULT_HOST,
        help=f"Ollama ホスト URL (default: {OLLAMA_DEFAULT_HOST})",
    )
    parser.add_argument(
        "--model", default=OLLAMA_DEFAULT_MODEL,
        help=f"Ollama モデル名 (default: {OLLAMA_DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="既に desc_text がある場合も上書きする",
    )
    parser.add_argument("--dry-run", action="store_true", help="対象件数のみ表示")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger(__name__)

    if not args.db_path or not args.db_path.exists():
        logger.error("DB が見つかりません: %s", args.db_path)
        sys.exit(1)

    conn = sqlite3.connect(str(args.db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    if args.dry_run:
        if args.force:
            count = conn.execute(
                "SELECT COUNT(*) FROM media WHERE desc_text IS NOT NULL AND desc_text != ''"
            ).fetchone()[0]
        else:
            count = conn.execute(
                "SELECT COUNT(*) FROM media "
                "WHERE desc_model IN ('tag-csv-v1', 'tag-based-v1') "
                "AND desc_text IS NOT NULL AND desc_text != ''"
            ).fetchone()[0]
        logger.info("対象: %d 件 (dry-run)", count)
        conn.close()
        return

    logger.info("Ollama: %s (model: %s)", args.host, args.model)

    updated = backfill_desc_text_ollama(
        conn,
        host=args.host,
        model=args.model,
        force=args.force,
    )

    logger.info("完了: %d 件の説明文を生成", updated)

    if updated > 0:
        logger.info("desc_embedding を再計算中...")
        n_emb = recompute_desc_embedding(conn)
        logger.info("desc_embedding 再計算: %d 件", n_emb)

    conn.close()


if __name__ == "__main__":
    main()
