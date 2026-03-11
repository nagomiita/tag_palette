"""Branching route CRUD operations."""

from __future__ import annotations

import sqlite3

def create_route(
    conn: sqlite3.Connection,
    *,
    novel_id: int,
    name: str,
    fork_from_chunk_id: int,
    merge_to_chunk_id: int | None = None,
    description: str | None = None,
) -> int:
    """Create a new route and return its id."""
    cur = conn.execute(
        """
        INSERT INTO routes (novel_id, name, description, fork_from_chunk_id, merge_to_chunk_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (novel_id, name, description, fork_from_chunk_id, merge_to_chunk_id),
    )
    conn.commit()
    return cur.lastrowid


def get_route(conn: sqlite3.Connection, route_id: int) -> dict | None:
    """Get a route by id."""
    row = conn.execute(
        "SELECT id, novel_id, name, description, fork_from_chunk_id, merge_to_chunk_id FROM routes WHERE id = ?",
        (route_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "novel_id": row[1],
        "name": row[2],
        "description": row[3],
        "fork_from_chunk_id": row[4],
        "merge_to_chunk_id": row[5],
    }


def list_routes(conn: sqlite3.Connection, novel_id: int) -> list[dict]:
    """List all routes for a novel."""
    rows = conn.execute(
        "SELECT id, name, description, fork_from_chunk_id, merge_to_chunk_id FROM routes WHERE novel_id = ? ORDER BY id",
        (novel_id,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "description": r[2],
            "fork_from_chunk_id": r[3],
            "merge_to_chunk_id": r[4],
        }
        for r in rows
    ]


def update_route(
    conn: sqlite3.Connection,
    route_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    merge_to_chunk_id: int | None = ...,
) -> None:
    """Update route fields. Pass merge_to_chunk_id=None to clear merge point."""
    updates = []
    params = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if merge_to_chunk_id is not ...:
        updates.append("merge_to_chunk_id = ?")
        params.append(merge_to_chunk_id)
    if not updates:
        return
    params.append(route_id)
    conn.execute(
        f"UPDATE routes SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()


def delete_route(conn: sqlite3.Connection, route_id: int) -> None:
    """Delete a route and its chunks."""
    conn.execute("DELETE FROM route_chunks WHERE route_id = ?", (route_id,))
    conn.execute("DELETE FROM routes WHERE id = ?", (route_id,))
    conn.commit()


def add_route_chunk(
    conn: sqlite3.Connection,
    route_id: int,
    seq: int,
    kind: str,
    body: str,
) -> int:
    """Add a chunk to a route. Returns the chunk id."""
    cur = conn.execute(
        "INSERT INTO route_chunks (route_id, seq, kind, body) VALUES (?, ?, ?, ?)",
        (route_id, seq, kind, body),
    )
    chunk_id = cur.lastrowid
    conn.commit()
    return chunk_id


def get_route_chunks(conn: sqlite3.Connection, route_id: int) -> list[dict]:
    """Get all chunks for a route, ordered by seq."""
    rows = conn.execute(
        "SELECT id, seq, kind, body FROM route_chunks WHERE route_id = ? ORDER BY seq",
        (route_id,),
    ).fetchall()
    return [
        {"id": r[0], "seq": r[1], "kind": r[2], "body": r[3]}
        for r in rows
    ]


def get_full_path(
    conn: sqlite3.Connection,
    route_id: int,
) -> list[dict]:
    """Get the full reading path: main chunks before fork, route chunks, main chunks after merge.

    Returns list of {"source": "main"|"route", "chunk_id": int, "seq": int, "kind": str, "body": str}.
    """
    route = get_route(conn, route_id)
    if route is None:
        return []

    novel_id = route["novel_id"]
    fork_chunk_id = route["fork_from_chunk_id"]
    merge_chunk_id = route["merge_to_chunk_id"]

    # Get fork chunk's seq
    fork_seq = conn.execute(
        "SELECT seq FROM novel_chunks WHERE id = ?", (fork_chunk_id,)
    ).fetchone()[0]

    # Main chunks up to and including fork point
    before = conn.execute(
        "SELECT id, seq, kind, body FROM novel_chunks WHERE novel_id = ? AND seq <= ? ORDER BY seq",
        (novel_id, fork_seq),
    ).fetchall()
    path = [
        {"source": "main", "chunk_id": r[0], "seq": r[1], "kind": r[2], "body": r[3]}
        for r in before
    ]

    # Route chunks
    route_chunks = get_route_chunks(conn, route_id)
    for rc in route_chunks:
        path.append({
            "source": "route",
            "chunk_id": rc["id"],
            "seq": rc["seq"],
            "kind": rc["kind"],
            "body": rc["body"],
        })

    # Main chunks from merge point onward
    if merge_chunk_id is not None:
        merge_seq = conn.execute(
            "SELECT seq FROM novel_chunks WHERE id = ?", (merge_chunk_id,)
        ).fetchone()[0]
        after = conn.execute(
            "SELECT id, seq, kind, body FROM novel_chunks WHERE novel_id = ? AND seq >= ? ORDER BY seq",
            (novel_id, merge_seq),
        ).fetchall()
        for r in after:
            path.append({
                "source": "main",
                "chunk_id": r[0],
                "seq": r[1],
                "kind": r[2],
                "body": r[3],
            })

    return path
