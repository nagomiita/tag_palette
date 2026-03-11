"""Tests for branching route CRUD operations."""

from pathlib import Path

from tag_palette.novel.db import connect, insert_chunks, insert_novel
from tag_palette.novel.route import (
    add_route_chunk,
    create_route,
    delete_route,
    get_full_path,
    get_route,
    get_route_chunks,
    list_routes,
    update_route,
)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "novel_test.db"

NOVEL_ID = 99980001


def _setup(conn):
    """テスト用の小説とチャンクを作成する。"""
    # Cleanup
    conn.execute("DELETE FROM route_chunks WHERE route_id IN (SELECT id FROM routes WHERE novel_id = ?)", (NOVEL_ID,))
    conn.execute("DELETE FROM routes WHERE novel_id = ?", (NOVEL_ID,))
    conn.execute("DELETE FROM chunk_embeddings WHERE chunk_id IN (SELECT id FROM novel_chunks WHERE novel_id = ?)", (NOVEL_ID,))
    conn.execute("DELETE FROM novel_chunk_morphemes WHERE chunk_id IN (SELECT id FROM novel_chunks WHERE novel_id = ?)", (NOVEL_ID,))
    conn.execute("DELETE FROM novel_chunks WHERE novel_id = ?", (NOVEL_ID,))
    conn.execute("DELETE FROM novels WHERE id = ?", (NOVEL_ID,))
    conn.commit()

    insert_novel(conn, novel_id=NOVEL_ID, title="route_test")
    chunk_ids = insert_chunks(conn, NOVEL_ID, [
        (0, "narrative", "勇者は旅に出た。"),
        (1, "narrative", "森の中で魔物に遭遇した。"),
        (2, "dialogue", "「戦うしかない！」"),
        (3, "narrative", "激しい戦闘が始まった。"),
        (4, "narrative", "勇者は魔物を倒した。"),
        (5, "narrative", "旅は続く。"),
    ])
    return chunk_ids


def test_create_and_get_route():
    """ルートの作成と取得ができること。"""
    conn = connect(DB_PATH)
    chunk_ids = _setup(conn)

    route_id = create_route(
        conn,
        novel_id=NOVEL_ID,
        name="if: 戦闘回避ルート",
        fork_from_chunk_id=chunk_ids[2],
        merge_to_chunk_id=chunk_ids[5],
        description="戦闘を避けて迂回する",
    )

    route = get_route(conn, route_id)
    assert route is not None
    assert route["name"] == "if: 戦闘回避ルート"
    assert route["fork_from_chunk_id"] == chunk_ids[2]
    assert route["merge_to_chunk_id"] == chunk_ids[5]

    conn.close()


def test_list_routes():
    """小説のルート一覧が取得できること。"""
    conn = connect(DB_PATH)
    chunk_ids = _setup(conn)

    create_route(conn, novel_id=NOVEL_ID, name="ルートA", fork_from_chunk_id=chunk_ids[1])
    create_route(conn, novel_id=NOVEL_ID, name="ルートB", fork_from_chunk_id=chunk_ids[3], merge_to_chunk_id=chunk_ids[5])

    routes = list_routes(conn, NOVEL_ID)
    assert len(routes) == 2
    assert routes[0]["name"] == "ルートA"
    assert routes[1]["name"] == "ルートB"

    conn.close()


def test_update_route():
    """ルートの更新ができること。"""
    conn = connect(DB_PATH)
    chunk_ids = _setup(conn)

    route_id = create_route(conn, novel_id=NOVEL_ID, name="仮ルート", fork_from_chunk_id=chunk_ids[1])

    update_route(conn, route_id, name="正式ルート", merge_to_chunk_id=chunk_ids[4])

    route = get_route(conn, route_id)
    assert route["name"] == "正式ルート"
    assert route["merge_to_chunk_id"] == chunk_ids[4]

    # merge_to を NULL に戻す
    update_route(conn, route_id, merge_to_chunk_id=None)
    route = get_route(conn, route_id)
    assert route["merge_to_chunk_id"] is None

    conn.close()


def test_add_and_get_route_chunks():
    """ルートにチャンクを追加・取得できること。"""
    conn = connect(DB_PATH)
    chunk_ids = _setup(conn)

    route_id = create_route(
        conn,
        novel_id=NOVEL_ID,
        name="if: 逃走ルート",
        fork_from_chunk_id=chunk_ids[2],
        merge_to_chunk_id=chunk_ids[5],
    )

    rc1 = add_route_chunk(conn, route_id, 0, "narrative", "勇者は逃げ出した。")
    rc2 = add_route_chunk(conn, route_id, 1, "dialogue", "「逃げるが勝ちだ！」")
    rc3 = add_route_chunk(conn, route_id, 2, "narrative", "森を抜けて安全な場所にたどり着いた。")

    chunks = get_route_chunks(conn, route_id)
    assert len(chunks) == 3
    assert chunks[0]["body"] == "勇者は逃げ出した。"
    assert chunks[1]["kind"] == "dialogue"
    assert chunks[2]["seq"] == 2

    print(f"\n  Route chunks: {len(chunks)}")

    conn.close()


def test_delete_route():
    """ルートの削除でチャンクも削除されること。"""
    conn = connect(DB_PATH)
    chunk_ids = _setup(conn)

    route_id = create_route(conn, novel_id=NOVEL_ID, name="削除テスト", fork_from_chunk_id=chunk_ids[0])
    add_route_chunk(conn, route_id, 0, "narrative", "テスト文。")

    delete_route(conn, route_id)

    assert get_route(conn, route_id) is None
    assert get_route_chunks(conn, route_id) == []

    conn.close()


def test_get_full_path_with_merge():
    """合流ありルートのフルパスが正しいこと。"""
    conn = connect(DB_PATH)
    chunk_ids = _setup(conn)

    # Fork after chunk[2] (「戦うしかない！」), merge at chunk[5] (旅は続く)
    route_id = create_route(
        conn,
        novel_id=NOVEL_ID,
        name="if: 回避",
        fork_from_chunk_id=chunk_ids[2],
        merge_to_chunk_id=chunk_ids[5],
    )
    add_route_chunk(conn, route_id, 0, "narrative", "勇者は身を隠した。")
    add_route_chunk(conn, route_id, 1, "narrative", "魔物は去っていった。")

    path = get_full_path(conn, route_id)

    # main[0..2] + route[0..1] + main[5]
    sources = [p["source"] for p in path]
    assert sources[:3] == ["main", "main", "main"]
    assert sources[3:5] == ["route", "route"]
    assert sources[5] == "main"

    print("\n  Full path (merge):")
    for p in path:
        print(f"    [{p['source']}] {p['kind']}: {p['body'][:30]}")

    conn.close()


def test_get_full_path_independent():
    """独立終了ルートのフルパスが正しいこと。"""
    conn = connect(DB_PATH)
    chunk_ids = _setup(conn)

    route_id = create_route(
        conn,
        novel_id=NOVEL_ID,
        name="if: バッドエンド",
        fork_from_chunk_id=chunk_ids[1],
    )
    add_route_chunk(conn, route_id, 0, "narrative", "勇者は力尽きた。")
    add_route_chunk(conn, route_id, 1, "narrative", "ゲームオーバー。")

    path = get_full_path(conn, route_id)

    # main[0..1] + route[0..1], no merge
    assert len(path) == 4
    sources = [p["source"] for p in path]
    assert sources == ["main", "main", "route", "route"]

    print("\n  Full path (independent):")
    for p in path:
        print(f"    [{p['source']}] {p['kind']}: {p['body'][:30]}")

    conn.close()
