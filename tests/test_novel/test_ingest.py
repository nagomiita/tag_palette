"""Integration test: ingest real novel files into novel_test.db."""

from pathlib import Path

from tag_palette.novel.db import connect
from tag_palette.novel.ingest import ingest_directory

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "novel_test.db"
INPUT_DIR = Path(r"C:\Users\taket\Downloads\novel_test")


def test_ingest_novels():
    """テスト用小説ファイルを取り込み、DBに保存されること。"""
    # Clean previous test data (novels with test IDs)
    conn = connect(DB_PATH)
    for novel_id in [20259818, 21985223]:
        conn.execute("DELETE FROM novel_chunk_morphemes WHERE chunk_id IN (SELECT id FROM novel_chunks WHERE novel_id = ?)", (novel_id,))
        conn.execute("DELETE FROM novel_chunks WHERE novel_id = ?", (novel_id,))
        conn.execute("DELETE FROM novel_tags WHERE novel_id = ?", (novel_id,))
        conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
    conn.commit()
    conn.close()

    results = ingest_directory(DB_PATH, INPUT_DIR)

    assert len(results) == 2

    # Verify data in DB
    conn = connect(DB_PATH)

    # Check novels
    novels = conn.execute("SELECT id, title FROM novels WHERE id IN (20259818, 21985223) ORDER BY id").fetchall()
    assert len(novels) == 2
    assert novels[0][1] == "ホムンクルスなりきり体験"

    # Check tags exist
    tag_count = conn.execute(
        "SELECT COUNT(*) FROM novel_tags WHERE novel_id = 20259818"
    ).fetchone()[0]
    assert tag_count > 0

    # Check chunks exist
    chunk_count = conn.execute(
        "SELECT COUNT(*) FROM novel_chunks WHERE novel_id = 20259818"
    ).fetchone()[0]
    assert chunk_count > 0

    # Check morphemes exist
    morpheme_count = conn.execute(
        """
        SELECT COUNT(*) FROM novel_chunk_morphemes cm
        JOIN novel_chunks c ON c.id = cm.chunk_id
        WHERE c.novel_id = 20259818
        """
    ).fetchone()[0]
    assert morpheme_count > 0

    # Print summary for manual verification
    for r in results:
        print(f"  Novel {r['novel_id']}: {r['title']} - {r['num_chunks']} chunks, {r['num_morpheme_types']} morpheme types")

    # Print sample chunks
    sample_chunks = conn.execute(
        "SELECT seq, kind, substr(body, 1, 50) FROM novel_chunks WHERE novel_id = 20259818 ORDER BY seq LIMIT 5"
    ).fetchall()
    print("\n  Sample chunks (novel 20259818):")
    for seq, kind, body in sample_chunks:
        print(f"    [{seq}] {kind}: {body}...")

    # Print sample morphemes
    sample_morphemes = conn.execute(
        """
        SELECT m.surface, m.pos, cm.count
        FROM novel_chunk_morphemes cm
        JOIN novel_morphemes m ON m.id = cm.morpheme_id
        JOIN novel_chunks c ON c.id = cm.chunk_id
        WHERE c.novel_id = 20259818
        ORDER BY cm.count DESC
        LIMIT 10
        """
    ).fetchall()
    print("\n  Top morphemes (novel 20259818):")
    for surface, pos, count in sample_morphemes:
        print(f"    {surface} ({pos}): {count}")

    conn.close()
