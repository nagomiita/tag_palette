"""Tests for novel DB initialization and CRUD."""

from pathlib import Path

from tag_palette.novel.db import (
    connect,
    insert_chunks,
    insert_morphemes,
    insert_novel,
    insert_tags,
)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "novel_test.db"


def test_schema_creation():
    """DB接続時にテーブルが作成されること。"""
    conn = connect(DB_PATH)
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    conn.close()
    assert "novels" in tables
    assert "tags" in tables
    assert "novel_tags" in tables
    assert "novel_chunks" in tables
    assert "novel_morphemes" in tables
    assert "novel_chunk_morphemes" in tables


def test_insert_novel():
    """作品を登録できること。"""
    conn = connect(DB_PATH)
    insert_novel(conn, novel_id=99999, title="テスト作品", author="テスト作者", url="https://example.com")
    row = conn.execute("SELECT id, title, author, url FROM novels WHERE id = 99999").fetchone()
    conn.close()
    assert row == (99999, "テスト作品", "テスト作者", "https://example.com")


def test_insert_tags():
    """タグを登録し作品に紐付けできること。"""
    conn = connect(DB_PATH)
    insert_novel(conn, novel_id=99998, title="タグテスト")
    insert_tags(conn, 99998, ["タグA", "タグB", "タグC"])
    rows = conn.execute(
        """
        SELECT t.name FROM tags t
        JOIN novel_tags nt ON nt.tag_id = t.id
        WHERE nt.novel_id = 99998
        ORDER BY t.name
        """
    ).fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["タグA", "タグB", "タグC"]


def test_insert_chunks():
    """チャンクを登録できること。"""
    conn = connect(DB_PATH)
    insert_novel(conn, novel_id=99997, title="チャンクテスト")
    chunk_ids = insert_chunks(conn, 99997, [
        (0, "narrative", "地の文テスト"),
        (1, "dialogue", "「台詞テスト」"),
        (2, "thought", "(心の声テスト)"),
    ])
    conn.close()
    assert len(chunk_ids) == 3


def test_insert_morphemes():
    """形態素を登録しチャンクに紐付けできること。"""
    conn = connect(DB_PATH)
    insert_novel(conn, novel_id=99996, title="形態素テスト")
    chunk_ids = insert_chunks(conn, 99996, [(0, "narrative", "テスト文")])
    insert_morphemes(conn, chunk_ids[0], {("テスト", "名詞"): 1, ("文", "名詞"): 1})
    rows = conn.execute(
        """
        SELECT m.surface, m.pos, cm.count
        FROM novel_chunk_morphemes cm
        JOIN novel_morphemes m ON m.id = cm.morpheme_id
        WHERE cm.chunk_id = ?
        ORDER BY m.surface
        """,
        (chunk_ids[0],),
    ).fetchall()
    conn.close()
    assert len(rows) == 2
