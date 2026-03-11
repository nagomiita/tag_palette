"""Tests for chunk embedding generation and similarity search."""

from pathlib import Path

import numpy as np

from tag_palette.novel.db import connect, insert_chunks, insert_novel
from tag_palette.novel.embedding import (
    embed_chunks,
    generate_embedding,
    load_embedding,
    save_embedding,
    search_similar,
)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "novel_test.db"


def test_generate_embedding():
    """embedding ベクトルが生成されること。"""
    emb = generate_embedding("剣を持った勇者が魔王に立ち向かう。")
    assert isinstance(emb, np.ndarray)
    assert emb.shape[0] > 0
    # normalized
    norm = np.linalg.norm(emb)
    assert abs(norm - 1.0) < 0.01


def test_save_and_load_embedding():
    """embedding の保存と読み出しが正しく行われること。"""
    conn = connect(DB_PATH)

    # Create test novel and chunk
    novel_id = 99990001
    conn.execute("DELETE FROM chunk_embeddings WHERE chunk_id IN (SELECT id FROM novel_chunks WHERE novel_id = ?)", (novel_id,))
    conn.execute("DELETE FROM novel_chunk_morphemes WHERE chunk_id IN (SELECT id FROM novel_chunks WHERE novel_id = ?)", (novel_id,))
    conn.execute("DELETE FROM novel_chunks WHERE novel_id = ?", (novel_id,))
    conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
    conn.commit()

    insert_novel(conn, novel_id=novel_id, title="embedding_test")
    chunk_ids = insert_chunks(conn, novel_id, [(0, "narrative", "テスト用の文章です。")])
    chunk_id = chunk_ids[0]

    emb = generate_embedding("テスト用の文章です。")
    save_embedding(conn, chunk_id, emb)

    loaded = load_embedding(conn, chunk_id)
    assert loaded is not None
    np.testing.assert_array_almost_equal(emb, loaded, decimal=5)

    # Cleanup
    conn.execute("DELETE FROM chunk_embeddings WHERE chunk_id = ?", (chunk_id,))
    conn.execute("DELETE FROM novel_chunks WHERE novel_id = ?", (novel_id,))
    conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
    conn.commit()
    conn.close()


def test_similarity_search():
    """類似チャンク検索が動作すること。"""
    conn = connect(DB_PATH)

    novel_id = 99990002
    conn.execute("DELETE FROM chunk_embeddings WHERE chunk_id IN (SELECT id FROM novel_chunks WHERE novel_id = ?)", (novel_id,))
    conn.execute("DELETE FROM novel_chunk_morphemes WHERE chunk_id IN (SELECT id FROM novel_chunks WHERE novel_id = ?)", (novel_id,))
    conn.execute("DELETE FROM novel_chunks WHERE novel_id = ?", (novel_id,))
    conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
    conn.commit()

    insert_novel(conn, novel_id=novel_id, title="similarity_test")
    texts = [
        "勇者は剣を抜いて魔王に斬りかかった。",
        "魔法使いは杖を構えて呪文を詠唱した。",
        "勇者の剣が魔王の鎧を貫いた。",
        "村人たちは平和な日常を送っていた。",
    ]
    chunk_ids = insert_chunks(
        conn, novel_id,
        [(i, "narrative", t) for i, t in enumerate(texts)],
    )

    for cid, text in zip(chunk_ids, texts):
        emb = generate_embedding(text)
        save_embedding(conn, cid, emb)

    # Search similar to "勇者は剣を抜いて魔王に斬りかかった。"
    results = search_similar(conn, chunk_ids[0], top_n=3, novel_id=novel_id)
    assert len(results) == 3

    # The most similar should be "勇者の剣が魔王の鎧を貫いた。" (chunk_ids[2])
    assert results[0][0] == chunk_ids[2]
    # Similarity should be > 0
    assert results[0][1] > 0

    print("\n  Similarity results:")
    for cid, sim in results:
        body = conn.execute("SELECT body FROM novel_chunks WHERE id = ?", (cid,)).fetchone()[0]
        print(f"    {sim:.4f}: {body}")

    # Cleanup
    for cid in chunk_ids:
        conn.execute("DELETE FROM chunk_embeddings WHERE chunk_id = ?", (cid,))
    conn.execute("DELETE FROM novel_chunks WHERE novel_id = ?", (novel_id,))
    conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
    conn.commit()
    conn.close()


def test_embed_chunks_batch():
    """embed_chunks で未処理チャンクを一括 embedding できること。"""
    conn = connect(DB_PATH)

    novel_id = 99990003
    conn.execute("DELETE FROM chunk_embeddings WHERE chunk_id IN (SELECT id FROM novel_chunks WHERE novel_id = ?)", (novel_id,))
    conn.execute("DELETE FROM novel_chunk_morphemes WHERE chunk_id IN (SELECT id FROM novel_chunks WHERE novel_id = ?)", (novel_id,))
    conn.execute("DELETE FROM novel_chunks WHERE novel_id = ?", (novel_id,))
    conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
    conn.commit()

    insert_novel(conn, novel_id=novel_id, title="batch_test")
    insert_chunks(conn, novel_id, [
        (0, "narrative", "朝の光が窓から差し込んだ。"),
        (1, "dialogue", "「おはよう」"),
    ])

    count = embed_chunks(conn, novel_id=novel_id)
    assert count == 2

    # Running again should return 0 (already embedded)
    count2 = embed_chunks(conn, novel_id=novel_id)
    assert count2 == 0

    # Cleanup
    conn.execute("DELETE FROM chunk_embeddings WHERE chunk_id IN (SELECT id FROM novel_chunks WHERE novel_id = ?)", (novel_id,))
    conn.execute("DELETE FROM novel_chunks WHERE novel_id = ?", (novel_id,))
    conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
    conn.commit()
    conn.close()
