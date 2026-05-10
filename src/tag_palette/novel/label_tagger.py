"""小説ラベル → タグマッチング。

マッチング戦略:
  1. タグの日本語名 (tags.name) とラベル名の完全一致 → similarity=1.0 で即紐付け
  2. 一致なし → Ollama LLM で英語キーワード生成 → 各キーワード個別にタグ埋め込みと
     コサイン類似度を計算し、キーワードごとの最も類似するタグを採用（平均化しない）

複数 Ollama サーバーへの並列分散リクエストに対応。

Usage:
    uv run python -m tag_palette.novel.label_tagger
    uv run python -m tag_palette.novel.label_tagger --dry-run
    uv run python -m tag_palette.novel.label_tagger --top-n 10 --model gemma3:12b
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from itertools import cycle

import numpy as np
from ollama import Client

from tag_palette.shared.env_config import get_db_path, get_ollama_hosts

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "huihui_ai/qwen2.5-abliterate:14b"
DEFAULT_TOP_N = 5
EXACT_MATCH_SIMILARITY = 1.0

_THINK_RE = re.compile(r"<think>.*?</think>\s*", flags=re.DOTALL)

_SYSTEM_PROMPT = """\
You are a tag translator for anime/manga illustration databases.
Given a Japanese label (keyword or phrase), output English keywords that correspond to danbooru-style tags.

Rules:
- Output ONLY a comma-separated list of English keywords (lowercase, underscores for spaces)
- Output 3-5 keywords that DIRECTLY describe the concept
- Use danbooru tag conventions (e.g. 1girl, blue_eyes, school_uniform)
- Only output tags that are strongly related to the input concept
- Do NOT output generic or loosely related tags
- Do NOT output explanations, just the tag list"""


def _generate_keywords(
    label_name: str,
    host: str,
    model: str,
) -> list[str]:
    """Ollama でラベル名から英語キーワードを生成する。"""
    client = Client(host=host)
    response = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": label_name},
        ],
        think=False,
    )
    raw = response["message"]["content"].strip()
    raw = _THINK_RE.sub("", raw).strip()
    keywords = [k.strip().lower().replace(" ", "_") for k in raw.split(",") if k.strip()]
    return keywords


def _generate_keywords_batch(
    labels: list[tuple[str, str]],
    hosts: list[str],
    model: str,
    max_workers: int | None = None,
) -> dict[str, list[str]]:
    """複数ラベルを複数 Ollama サーバーに並列分散して処理する。"""
    if max_workers is None:
        max_workers = len(hosts)

    host_cycle = cycle(hosts)
    results: dict[str, list[str]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for label_id, label_name in labels:
            host = next(host_cycle)
            future = executor.submit(_generate_keywords, label_name, host, model)
            futures[future] = (label_id, label_name)

        for future in as_completed(futures):
            label_id, label_name = futures[future]
            try:
                keywords = future.result()
                results[label_id] = keywords
                logger.info("  %s -> %s", label_name, ", ".join(keywords))
            except Exception as e:
                logger.warning("  %s: Ollama error: %s", label_name, e)
                results[label_id] = []

    return results


def _load_tag_embeddings_from_db(
    conn: sqlite3.Connection,
) -> tuple[list[str], np.ndarray]:
    """DB から全タグの埋め込みを読み込む。"""
    rows = conn.execute(
        "SELECT tag_id, embedding FROM tag_embeddings WHERE embedding IS NOT NULL"
    ).fetchall()

    tag_ids = []
    vectors = []
    for tag_id, emb_bytes in rows:
        tag_ids.append(tag_id)
        vectors.append(np.frombuffer(emb_bytes, dtype=np.float32))

    return tag_ids, np.array(vectors, dtype=np.float32)


def _build_name_to_tag_id(conn: sqlite3.Connection) -> dict[str, str]:
    """タグの日本語名 → tag_id のマッピングを構築する。"""
    name_map: dict[str, str] = {}
    rows = conn.execute("SELECT id, name FROM tags WHERE name IS NOT NULL").fetchall()
    for tag_id, name in rows:
        if name:
            name_map[name] = tag_id
            # tag_id 自体（英語名）もマッピング
            name_map[tag_id] = tag_id
    return name_map


def _match_keywords_to_tags(
    keywords: list[str],
    tag_ids: list[str],
    tag_matrix: np.ndarray,
    top_n: int,
    exclude_tag_ids: set[str] | None = None,
) -> list[tuple[str, float]]:
    """各キーワード個別に最も類似するタグを返す（平均化しない）。

    各キーワードごとに最も類似度の高いタグを1つ選び、重複を排除して
    similarity 降順で top_n 件を返す。
    """
    if not keywords:
        return []

    from tag_palette.shared.embedding import _get_model

    model = _get_model()
    readable = [kw.replace("_", " ") for kw in keywords]
    kw_vectors = model.encode(readable, normalize_embeddings=True)
    kw_matrix = np.array(kw_vectors, dtype=np.float32)

    sim_matrix = kw_matrix @ tag_matrix.T  # (n_keywords, n_tags)

    # 各キーワードの best match を収集（重複タグは最大 similarity を採用）
    best_matches: dict[str, float] = {}
    for kw_idx in range(len(keywords)):
        sorted_indices = np.argsort(sim_matrix[kw_idx])[::-1]
        for tag_idx in sorted_indices:
            tid = tag_ids[tag_idx]
            if exclude_tag_ids and tid in exclude_tag_ids:
                continue
            sim = float(sim_matrix[kw_idx, tag_idx])
            if tid not in best_matches or sim > best_matches[tid]:
                best_matches[tid] = sim
            break  # このキーワードの best 1 件のみ

    # similarity 降順で top_n
    sorted_matches = sorted(best_matches.items(), key=lambda x: x[1], reverse=True)
    return sorted_matches[:top_n]


def sync_label_tags(
    conn: sqlite3.Connection,
    *,
    model: str = DEFAULT_MODEL,
    top_n: int = DEFAULT_TOP_N,
    force: bool = False,
) -> int:
    """全ラベルのタグマッチングを実行し novel_label_tags に書き込む。"""
    hosts = get_ollama_hosts()
    logger.info("Ollama hosts: %s", hosts)

    # 対象ラベルを取得
    if force:
        rows = conn.execute("SELECT id, name FROM novel_labels").fetchall()
    else:
        rows = conn.execute(
            "SELECT nl.id, nl.name FROM novel_labels nl "
            "WHERE nl.id NOT IN (SELECT DISTINCT novel_label_id FROM novel_label_tags)"
        ).fetchall()

    if not rows:
        logger.info("タグマッチング対象ラベルなし")
        return 0

    labels = [(r[0], r[1]) for r in rows]
    logger.info("対象ラベル: %d 件", len(labels))

    # force の場合は先に既存データを削除
    if force:
        label_ids = [lid for lid, _ in labels]
        placeholders = ",".join("?" for _ in label_ids)
        conn.execute(f"DELETE FROM novel_label_tags WHERE novel_label_id IN ({placeholders})", label_ids)
        conn.commit()

    # ── Phase 1: タグ名とラベル名の完全一致 ──
    logger.info("=== Phase 1: 完全一致マッチング ===")
    name_map = _build_name_to_tag_id(conn)

    now = datetime.now().isoformat()
    inserted = 0
    exact_matched_labels: set[str] = set()
    need_ollama: list[tuple[str, str]] = []

    for label_id, label_name in labels:
        matched_tag_id = name_map.get(label_name)
        if matched_tag_id:
            row_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO novel_label_tags (id, novel_label_id, tag_id, similarity, created_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(novel_label_id, tag_id) DO UPDATE SET similarity = excluded.similarity",
                (row_id, label_id, matched_tag_id, EXACT_MATCH_SIMILARITY, now),
            )
            inserted += 1
            exact_matched_labels.add(label_id)
            logger.info("  [exact] %s -> %s", label_name, matched_tag_id)
        else:
            need_ollama.append((label_id, label_name))

    conn.commit()
    logger.info("完全一致: %d 件, Ollama 対象: %d 件", len(exact_matched_labels), len(need_ollama))

    if not need_ollama:
        logger.info("novel_label_tags 登録完了: %d 件", inserted)
        return inserted

    # ── Phase 2: Ollama + embedding マッチング ──
    logger.info("=== Phase 2: Ollama キーワード → 類似度マッチング ===")

    tag_ids, tag_matrix = _load_tag_embeddings_from_db(conn)
    logger.info("タグ埋め込み: %d 件", len(tag_ids))

    from tag_palette.shared.embedding import load_tag_embeddings
    load_tag_embeddings()

    keywords_map = _generate_keywords_batch(need_ollama, hosts, model)

    logger.info("タグマッチング中...")
    for label_id, label_name in need_ollama:
        keywords = keywords_map.get(label_id, [])
        if not keywords:
            continue

        # 完全一致で既に紐付いたタグを除外
        existing = {
            r[0] for r in conn.execute(
                "SELECT tag_id FROM novel_label_tags WHERE novel_label_id = ?", (label_id,)
            ).fetchall()
        }

        matches = _match_keywords_to_tags(keywords, tag_ids, tag_matrix, top_n, exclude_tag_ids=existing)
        for tag_id, similarity in matches:
            row_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO novel_label_tags (id, novel_label_id, tag_id, similarity, created_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(novel_label_id, tag_id) DO UPDATE SET similarity = excluded.similarity",
                (row_id, label_id, tag_id, similarity, now),
            )
            inserted += 1

        if inserted % 100 == 0:
            conn.commit()

    conn.commit()
    logger.info("novel_label_tags 登録完了: %d 件", inserted)
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="小説ラベル → タグマッチング")
    parser.add_argument("--db-path", type=str, default=None, help="SQLite DB パス")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Ollama モデル名")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="ラベルあたりの上位タグ数")
    parser.add_argument("--force", action="store_true", help="既存マッチングを再生成")
    parser.add_argument("--dry-run", action="store_true", help="キーワード生成のみ (DB 書き込みなし)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    db_path = args.db_path or str(get_db_path())
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    if args.dry_run:
        hosts = get_ollama_hosts()
        rows = conn.execute("SELECT id, name FROM novel_labels LIMIT 10").fetchall()
        labels = [(r[0], r[1]) for r in rows]
        logger.info("dry-run: %d ラベルでキーワード生成テスト", len(labels))
        results = _generate_keywords_batch(labels, hosts, args.model)
        for label_id, keywords in results.items():
            name = next(n for lid, n in labels if lid == label_id)
            logger.info("  %s -> %s", name, ", ".join(keywords))
        conn.close()
        return

    try:
        inserted = sync_label_tags(conn, model=args.model, top_n=args.top_n, force=args.force)
        logger.info("完了: %d 件登録", inserted)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
