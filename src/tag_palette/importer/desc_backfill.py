"""desc_text / desc_embedding のバックフィル。

desc_text の生成方法:
  - tag-csv: タグのカンマ区切り (高速、フォールバック)
  - ollama:  Ollama LLM による自然言語説明文 (高品質)
"""

from __future__ import annotations

import logging
import sqlite3

import numpy as np

logger = logging.getLogger(__name__)

DESC_MODEL_CSV = "tag-csv-v1"
DESC_MODEL_OLLAMA = "ollama-v1"
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"

OLLAMA_DEFAULT_MODEL = "huihui_ai/qwen3.5-abliterated:9b"


def _default_ollama_host() -> str:
    """環境変数から Ollama ホストを1つ返す（desc 生成は単一ホストで十分）。"""
    from tag_palette.shared.env_config import get_ollama_hosts

    return get_ollama_hosts()[0]


def _load_embedding_model():
    """Load the sentence-transformer on the preferred torch device."""
    from sentence_transformers import SentenceTransformer

    from tag_palette.shared.device import get_torch_device

    device = get_torch_device()
    logger.info("SentenceTransformer model loaded (device=%s)", device)
    return SentenceTransformer(
        EMBEDDING_MODEL_NAME,
        device=device,
        local_files_only=True,
    )


_OLLAMA_SYSTEM_PROMPT = """\
あなたはイラスト・画像の説明文を生成するアシスタントです。
ユーザーから画像に付与されたタグの一覧が与えられます。
タグの一覧から、その画像の内容を簡潔に日本語で説明してください。

ルール:
- 2〜4文程度で簡潔にまとめる
- キャラクター名、作品名があれば含める
- 構図、服装、表情、背景など視覚的な要素を自然な文で記述する
- タグをそのまま羅列するのではなく、自然な日本語の文章にする
- 出力は説明文のみ。前置きや注釈は不要"""


def _fetch_tags_by_media(
    conn: sqlite3.Connection,
    media_ids: list[str],
) -> dict[str, list[str]]:
    """media_ids に対応するタグを confidence 降順で取得する。"""
    placeholders = ",".join("?" for _ in media_ids)
    tag_rows = conn.execute(
        f"""
        SELECT mt.media_id, t.name, mt.confidence
        FROM media_tags mt
        JOIN tags t ON t.id = mt.tag_id
        WHERE mt.media_id IN ({placeholders})
        ORDER BY mt.media_id, mt.confidence DESC
        """,
        media_ids,
    ).fetchall()

    tags_by_media: dict[str, list[str]] = {mid: [] for mid in media_ids}
    for media_id, tag_name, _conf in tag_rows:
        if tag_name:
            tags_by_media[media_id].append(tag_name)
    return tags_by_media


def _pending_media_ids(conn: sqlite3.Connection) -> list[str]:
    """desc_text が NULL のメディア ID を返す。"""
    return [
        r[0]
        for r in conn.execute(
            "SELECT id FROM media WHERE desc_text IS NULL OR desc_text = ''"
        ).fetchall()
    ]


def _backfill_desc_text_csv(conn: sqlite3.Connection) -> int:
    """desc_text が NULL のメディアにタグのカンマ区切りを埋める。"""
    media_ids = _pending_media_ids(conn)
    if not media_ids:
        return 0

    tags_by_media = _fetch_tags_by_media(conn, media_ids)

    updated = 0
    for media_id in media_ids:
        tag_list = tags_by_media.get(media_id, [])
        if not tag_list:
            continue
        description = ", ".join(tag_list)
        conn.execute(
            "UPDATE media SET desc_text = ?, desc_model = ? WHERE id = ?",
            (description, DESC_MODEL_CSV, media_id),
        )
        updated += 1

    conn.commit()
    return updated


def _generate_desc_ollama(
    tags: list[str],
    host: str | None = None,
    model: str = OLLAMA_DEFAULT_MODEL,
) -> str:
    """Ollama にタグ一覧を渡して説明文を生成する。"""
    from ollama import Client

    host = host or _default_ollama_host()
    client = Client(host=host)
    tag_text = ", ".join(tags)

    response = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": _OLLAMA_SYSTEM_PROMPT},
            {"role": "user", "content": tag_text},
        ],
        think=False,
    )
    return response["message"]["content"].strip()


def backfill_desc_text_ollama(
    conn: sqlite3.Connection,
    *,
    host: str | None = None,
    model: str = OLLAMA_DEFAULT_MODEL,
    force: bool = False,
) -> int:
    """Ollama を使って desc_text に自然言語の説明文を埋める。

    対象: desc_model が 'tag-csv-v1' または 'tag-based-v1' のメディア
    （タグ羅列が desc_text に入っている状態のものを自然言語に変換する）

    Args:
        conn: SQLite 接続
        host: Ollama ホスト URL
        model: 使用するモデル名
        force: True なら Ollama 生成済みも含めて全件上書き
    """
    if force:
        rows = conn.execute(
            "SELECT id, desc_text FROM media "
            "WHERE desc_text IS NOT NULL AND desc_text != ''"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, desc_text FROM media "
            "WHERE desc_model IN ('tag-csv-v1', 'tag-based-v1') "
            "AND desc_text IS NOT NULL AND desc_text != ''"
        ).fetchall()

    if not rows:
        return 0

    host = host or _default_ollama_host()
    logger.info("Ollama desc 対象: %d 件 (host=%s)", len(rows), host)

    updated = 0
    for i, (media_id, desc_text) in enumerate(rows):
        try:
            # desc_text のタグ羅列をそのままリスト化してOllamaに渡す
            tags = [t.strip() for t in desc_text.split(",") if t.strip()]
            if not tags:
                continue

            description = _generate_desc_ollama(tags, host=host, model=model)
            conn.execute(
                "UPDATE media SET desc_text = ?, desc_model = ? WHERE id = ?",
                (description, f"{DESC_MODEL_OLLAMA}:{model}", media_id),
            )
            updated += 1
            logger.info("  [%d/%d] %s: %s", i + 1, len(rows), media_id, description)

            if updated % 50 == 0:
                conn.commit()

        except Exception as e:
            logger.warning("Ollama desc 生成失敗: %s -> %s", media_id, e)

    conn.commit()
    return updated


def recompute_desc_embedding(conn: sqlite3.Connection) -> int:
    """Ollama で更新された desc_text の desc_embedding を再計算する。

    対象: desc_model が 'ollama-v1:*' のメディア。
    """
    pattern = f"{DESC_MODEL_OLLAMA}:%"
    rows = conn.execute(
        """
        SELECT m.id, m.desc_text
        FROM media m
        JOIN media_embeddings me ON me.media_id = m.id
        WHERE m.desc_model LIKE ?
          AND m.desc_text IS NOT NULL
          AND m.desc_text != ''
        """,
        (pattern,),
    ).fetchall()

    if not rows:
        return 0

    st_model = _load_embedding_model()
    texts = [r[1] for r in rows]
    embeddings = st_model.encode(
        texts, normalize_embeddings=True, show_progress_bar=len(texts) > 100,
    )

    for (media_id, _), emb in zip(rows, embeddings):
        blob = emb.astype(np.float32).tobytes()
        conn.execute(
            "UPDATE media_embeddings SET desc_embedding = ? WHERE media_id = ?",
            (blob, media_id),
        )
    conn.commit()
    return len(rows)


def _backfill_desc_embedding(conn: sqlite3.Connection) -> int:
    """desc_embedding が NULL のメディアに embedding を生成して埋める。"""
    rows = conn.execute(
        """
        SELECT m.id, m.desc_text
        FROM media m
        JOIN media_embeddings me ON me.media_id = m.id
        WHERE me.desc_embedding IS NULL
          AND m.desc_text IS NOT NULL
          AND m.desc_text != ''
        """
    ).fetchall()

    if not rows:
        return 0

    model = _load_embedding_model()
    texts = [r[1] for r in rows]
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=len(texts) > 100)

    for (media_id, _), emb in zip(rows, embeddings):
        blob = emb.astype(np.float32).tobytes()
        conn.execute(
            "UPDATE media_embeddings SET desc_embedding = ? WHERE media_id = ?",
            (blob, media_id),
        )
    conn.commit()
    return len(rows)


def post_import_desc(conn: sqlite3.Connection) -> None:
    """インポート後に desc_text (CSV版) と desc_embedding を補完する。"""
    n_desc = _backfill_desc_text_csv(conn)
    if n_desc:
        logger.info("desc_text 生成: %d 件", n_desc)

    n_emb = _backfill_desc_embedding(conn)
    if n_emb:
        logger.info("desc_embedding 生成: %d 件", n_emb)

    if not n_desc and not n_emb:
        logger.info("desc 補完: 対象なし")
