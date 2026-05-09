"""Ingest novel files (.txt / .pdf) into the production local.db (UUID-based schema).

Usage:
    python src/tag_palette/novel/ingest_local.py [input_dir] [--db <path>] [--dry-run]

Reads NOVELS_DIR and SQLITE_DB_PATH from .env (dotenv).
CLI arguments override .env values.

Supported formats:
    .txt  — Pixiv novel text ({pixiv_id}_{title}.txt)
    .pdf  — なろう PDF novel ({n_code}.pdf) → series + chapters
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

try:
    from .chunker import chunk_text
    from .morpheme import extract_morphemes
    from .pdf_parser import parse_pdf, parse_pdf_as_series
except ImportError:
    from chunker import chunk_text
    from morpheme import extract_morphemes
    from pdf_parser import parse_pdf, parse_pdf_as_series

# Load .env from project root
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_ENV_PATH)


def _env_path(key: str) -> Path | None:
    val = os.getenv(key)
    if val:
        return Path(val)
    return None

BATCH_SIZE = 500


def _to_library_relative_path(file_path: Path) -> str | None:
    """Convert absolute path to Eagle library relative path (images/…).

    Example: D:\\eagle.library\\images\\XXX.info\\file.pdf
           → images/XXX.info/file.pdf
    """
    parts = file_path.resolve().parts
    try:
        idx = [p.lower() for p in parts].index("images")
    except ValueError:
        return None
    return "/".join(parts[idx:])


def _new_id() -> str:
    return uuid.uuid4().hex


_SENSITIVE_TAGS = {"18禁", "R-18", "R18"}


def _purge_novel(conn: sqlite3.Connection, novel_id: str) -> bool:
    """Delete a novel and all related data (CASCADE handles child tables)."""
    cur = conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
    return cur.rowcount > 0


def _purge_series(conn: sqlite3.Connection, series_id: str) -> int:
    """Delete all novels in a series, then the series itself."""
    cur = conn.execute("DELETE FROM novels WHERE series_id = ?", (series_id,))
    count = cur.rowcount
    conn.execute("DELETE FROM novel_series WHERE id = ?", (series_id,))
    return count


def _check_sensitive_tags(tags: list[str]) -> bool:
    """Check if any tag indicates sensitive content."""
    return any(t.strip() in _SENSITIVE_TAGS for t in tags)


def _parse_txt_file(file_path: Path) -> dict:
    """Parse a novel text file (Pixiv or Fanbox format).

    Pixiv format: line 6 starts with "Tags:" followed by body at line 8+.
    Fanbox/tagless format: no Tags line, body starts at line 6+.
    """
    stem = file_path.stem
    novel_id = stem.split("_", 1)[0]  # Pixiv ID as string
    title = stem.split("_", 1)[1] if "_" in stem else stem

    text = file_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    url = lines[0].strip() if len(lines) > 0 else ""
    author = lines[2].strip() if len(lines) > 2 else ""
    tag_line = lines[6].strip() if len(lines) > 6 else ""

    tags: list[str] = []
    if tag_line.startswith("Tags:"):
        tags = [t.strip() for t in tag_line[5:].split(",") if t.strip()]
        body = "\n".join(lines[8:])
    else:
        # No Tags line — body starts at line 6
        body = "\n".join(lines[6:])

    return {
        "novel_id": novel_id,
        "title": title,
        "author": author,
        "url": url,
        "tags": tags,
        "body": body,
        "is_sensitive": _check_sensitive_tags(tags),
    }


def _ensure_label(conn: sqlite3.Connection, name: str) -> str:
    """Get or create a novel_label, return its id."""
    row = conn.execute(
        "SELECT id FROM novel_labels WHERE name = ?", (name,)
    ).fetchone()
    if row:
        return row[0]
    label_id = _new_id()
    conn.execute(
        "INSERT INTO novel_labels (id, name) VALUES (?, ?)",
        (label_id, name),
    )
    return label_id


def _auto_label_from_master(
    conn: sqlite3.Connection, title: str, body: str,
) -> list[str]:
    """Match existing novel_labels against title+body by substring search.

    Returns list of matched label names.
    """
    rows = conn.execute("SELECT name FROM novel_labels ORDER BY length(name) DESC").fetchall()
    text = title + "\n" + body
    matched: list[str] = []
    for (name,) in rows:
        if len(name) >= 2 and name in text:
            matched.append(name)
    return matched


def _ensure_morpheme(
    conn: sqlite3.Connection,
    cache: dict[tuple[str, str], str],
    surface: str,
    pos: str,
) -> str:
    """Get or create a novel_morpheme, return its id. Uses in-memory cache."""
    key = (surface, pos)
    if key in cache:
        return cache[key]
    row = conn.execute(
        "SELECT id FROM novel_morphemes WHERE surface = ? AND pos = ?",
        (surface, pos),
    ).fetchone()
    if row:
        cache[key] = row[0]
        return row[0]
    morph_id = _new_id()
    conn.execute(
        "INSERT INTO novel_morphemes (id, surface, pos) VALUES (?, ?, ?)",
        (morph_id, surface, pos),
    )
    cache[key] = morph_id
    return morph_id


def _assign_labels(
    conn: sqlite3.Connection,
    novel_id: str,
    title: str,
    body: str,
    explicit_tags: list[str] | None = None,
) -> None:
    """Assign labels: explicit tags (Pixiv等) + auto-labels from master.

    Pixiv のように作者付与タグがある場合でも、既存 master 語との一致は
    追加で付与する。重複は除外。
    """
    tag_names = list(explicit_tags) if explicit_tags else []
    auto = _auto_label_from_master(conn, title, body)
    seen = {t.strip() for t in tag_names if t.strip()}
    new_auto = [name for name in auto if name not in seen]
    if new_auto:
        tag_names.extend(new_auto)
        print(f"    Auto-labeled: {', '.join(new_auto[:10])}{'...' if len(new_auto) > 10 else ''}")

    for tag_name in tag_names:
        tag_name = tag_name.strip()
        if not tag_name:
            continue
        label_id = _ensure_label(conn, tag_name)
        assoc_id = _new_id()
        conn.execute(
            "INSERT OR IGNORE INTO novel_label_associations (id, novel_id, label_id) VALUES (?, ?, ?)",
            (assoc_id, novel_id, label_id),
        )


def _ingest_novel_chunks(
    conn: sqlite3.Connection,
    novel_id: str,
    body: str,
    morph_cache: dict,
) -> tuple[int, int]:
    """Chunk text, extract morphemes, and insert into DB.

    Returns (num_chunks, num_morpheme_types).
    """
    chunks = chunk_text(body)
    chunk_ids: list[str] = []
    for c in chunks:
        chunk_id = _new_id()
        chunk_ids.append(chunk_id)
        conn.execute(
            "INSERT INTO novel_chunks (id, novel_id, seq, kind, body) VALUES (?, ?, ?, ?, ?)",
            (chunk_id, novel_id, c.seq, c.kind, c.body),
        )

    total_morphemes = 0
    cm_batch: list[tuple] = []
    for chunk, chunk_id in zip(chunks, chunk_ids):
        morpheme_counts = extract_morphemes(chunk.body)
        for (surface, pos), count in morpheme_counts.items():
            morph_id = _ensure_morpheme(conn, morph_cache, surface, pos)
            cm_batch.append((_new_id(), chunk_id, morph_id, count))
        total_morphemes += len(morpheme_counts)

        if len(cm_batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT INTO novel_chunk_morphemes (id, chunk_id, morpheme_id, count) VALUES (?, ?, ?, ?)",
                cm_batch,
            )
            cm_batch.clear()

    if cm_batch:
        conn.executemany(
            "INSERT INTO novel_chunk_morphemes (id, chunk_id, morpheme_id, count) VALUES (?, ?, ?, ?)",
            cm_batch,
        )

    return len(chunks), total_morphemes


def ingest_txt_file(
    conn: sqlite3.Connection, file_path: Path, morph_cache: dict, *, reingest: bool = False,
) -> dict:
    """Process a single .txt novel file into the DB.

    Returns summary stats.
    """
    data = _parse_txt_file(file_path)
    novel_id = data["novel_id"]

    # Skip if already exists (unless reingest)
    existing = conn.execute(
        "SELECT id FROM novels WHERE id = ?", (novel_id,)
    ).fetchone()
    if existing:
        if not reingest:
            return {
                "novel_id": novel_id,
                "title": data["title"],
                "skipped": True,
            }
        _purge_novel(conn, novel_id)
        print(f"    Purged existing: {novel_id}")

    # 1. Insert novel
    conn.execute(
        "INSERT INTO novels (id, title, author, url, is_sensitive, source_path) VALUES (?, ?, ?, ?, ?, ?)",
        (novel_id, data["title"], data["author"], data["url"], data.get("is_sensitive", False),
         _to_library_relative_path(file_path)),
    )

    # 2. Labels (tags)
    _assign_labels(conn, novel_id, data["title"], data["body"], data["tags"] or None)

    # 3. Chunks + morphemes
    num_chunks, num_morphemes = _ingest_novel_chunks(conn, novel_id, data["body"], morph_cache)

    conn.commit()

    return {
        "novel_id": novel_id,
        "title": data["title"],
        "num_chunks": num_chunks,
        "num_morpheme_types": num_morphemes,
        "skipped": False,
    }


def _ingest_pdf_single(
    conn: sqlite3.Connection, file_path: Path, morph_cache: dict, *, reingest: bool = False,
) -> dict:
    """Process a なろう PDF with no chapters as a single novel (no series)."""
    novel = parse_pdf(file_path)
    novel_id = novel.n_code

    existing = conn.execute(
        "SELECT id FROM novels WHERE id = ?", (novel_id,)
    ).fetchone()
    if existing:
        if not reingest:
            return {
                "novel_id": novel_id,
                "title": novel.title,
                "skipped": True,
            }
        _purge_novel(conn, novel_id)
        print(f"    Purged existing: {novel_id}")

    conn.execute(
        "INSERT INTO novels (id, title, author, url, is_sensitive, source_path) VALUES (?, ?, ?, ?, ?, ?)",
        (novel_id, novel.title, novel.author, novel.url, novel.is_sensitive,
         _to_library_relative_path(file_path)),
    )

    _assign_labels(conn, novel_id, novel.title, novel.body)

    num_chunks, num_morphemes = _ingest_novel_chunks(
        conn, novel_id, novel.body, morph_cache,
    )

    conn.commit()

    return {
        "novel_id": novel_id,
        "title": novel.title,
        "num_chunks": num_chunks,
        "num_morpheme_types": num_morphemes,
        "skipped": False,
    }


def ingest_pdf_file(
    conn: sqlite3.Connection, file_path: Path, morph_cache: dict, *, reingest: bool = False,
) -> dict:
    """Process a なろう PDF file.

    If chapters are detected (Bold titles), creates series + chapter novels.
    Otherwise, registers as a single novel without series.
    """
    series = parse_pdf_as_series(file_path)

    # No chapters found -> single novel
    if not series.chapters:
        return _ingest_pdf_single(conn, file_path, morph_cache, reingest=reingest)

    series_id = series.n_code

    # 1. Insert series
    existing_series = conn.execute(
        "SELECT id FROM novel_series WHERE id = ?", (series_id,)
    ).fetchone()
    if reingest:
        # Purge any single novel with same ID (from previous non-series import)
        if _purge_novel(conn, series_id):
            print(f"    Purged existing novel: {series_id}")
        if existing_series:
            count = _purge_series(conn, series_id)
            print(f"    Purged existing series: {series_id} ({count} chapters)")
            existing_series = None
    if not existing_series:
        conn.execute(
            "INSERT INTO novel_series (id, name) VALUES (?, ?)",
            (series_id, series.title),
        )

    # 2. Insert each chapter as a novel (skip existing chapters unless reingest)
    total_chunks = 0
    total_morphemes = 0
    ingested_chapters = 0
    skipped_chapters = 0
    for chapter in series.chapters:
        novel_id = f"{series_id}_{chapter.seq}"

        existing_novel = conn.execute(
            "SELECT id FROM novels WHERE id = ?", (novel_id,)
        ).fetchone()
        if existing_novel:
            if not reingest:
                skipped_chapters += 1
                continue
            _purge_novel(conn, novel_id)

        conn.execute(
            "INSERT INTO novels (id, title, author, url, description, is_sensitive, series_id, series_seq, source_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (novel_id, chapter.title, series.author, series.url,
             series.description, series.is_sensitive, series_id, chapter.seq,
             _to_library_relative_path(file_path)),
        )

        _assign_labels(conn, novel_id, chapter.title, chapter.body)

        num_chunks, num_morphemes = _ingest_novel_chunks(
            conn, novel_id, chapter.body, morph_cache,
        )
        total_chunks += num_chunks
        total_morphemes += num_morphemes
        ingested_chapters += 1

        print(f"    Ch.{chapter.seq}: {chapter.title} - {num_chunks} chunks")

    conn.commit()

    if ingested_chapters == 0:
        return {
            "novel_id": series_id,
            "title": series.title,
            "skipped": True,
        }

    return {
        "novel_id": series_id,
        "title": series.title,
        "num_chapters": ingested_chapters,
        "num_chapters_skipped": skipped_chapters,
        "num_chunks": total_chunks,
        "num_morpheme_types": total_morphemes,
        "skipped": False,
    }


def ingest_file(
    conn: sqlite3.Connection, file_path: Path, morph_cache: dict, *, reingest: bool = False,
) -> dict:
    """Process a single novel file into the production DB.

    Dispatches to txt or pdf handler based on file extension.
    """
    if file_path.suffix.lower() == ".pdf":
        return ingest_pdf_file(conn, file_path, morph_cache, reingest=reingest)
    return ingest_txt_file(conn, file_path, morph_cache, reingest=reingest)


def ingest_files(
    db_path: Path,
    file_paths: list[Path],
    *,
    dry_run: bool = False,
    reingest: bool = False,
) -> list[dict]:
    """Process explicit file paths into the production DB."""
    files = [f for f in file_paths if f.suffix.lower() in (".txt", ".pdf")]
    print(f"DB:    {db_path}")
    print(f"Files: {len(files)}")

    if dry_run:
        for f in files:
            stem = f.stem
            novel_id = stem.split("_", 1)[0]
            title = stem.split("_", 1)[1] if "_" in stem else stem
            print(f"  [{novel_id}] {title} ({f.suffix}) <- {f}")
        print(f"\n--dry-run: {len(files)} files found, no data written.")
        return []

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    morph_cache: dict[tuple[str, str], str] = {}
    results = []
    for i, f in enumerate(files, 1):
        result = ingest_file(conn, f, morph_cache, reingest=reingest)
        if result.get("skipped"):
            print(f"  [{i}/{len(files)}] SKIP {result['novel_id']} {result['title']}")
        elif result.get("num_chapters"):
            print(
                f"  [{i}/{len(files)}] {result['novel_id']} {result['title']}"
                f" - {result['num_chapters']} chapters, {result['num_chunks']} chunks, {result['num_morpheme_types']} morphemes"
            )
        else:
            print(
                f"  [{i}/{len(files)}] {result['novel_id']} {result['title']}"
                f" - {result['num_chunks']} chunks, {result['num_morpheme_types']} morphemes"
            )
        results.append(result)

    conn.close()

    ingested_results = [r for r in results if not r.get("skipped")]
    skipped_results = [r for r in results if r.get("skipped")]

    print(f"\n{'=' * 50}")
    if ingested_results:
        print(f"Ingested ({len(ingested_results)}):")
        for r in ingested_results:
            if r.get("num_chapters"):
                print(f"  {r['novel_id']} {r['title']} ({r['num_chapters']} chapters, {r['num_chunks']} chunks)")
            else:
                print(f"  {r['novel_id']} {r['title']} ({r['num_chunks']} chunks)")
    if skipped_results:
        print(f"Skipped ({len(skipped_results)}):")
        for r in skipped_results:
            print(f"  {r['novel_id']} {r['title']}")
    print(f"{'=' * 50}")
    print(f"Done: {len(ingested_results)} ingested, {len(skipped_results)} skipped.")
    return results


def ingest_directory(
    db_path: Path,
    input_dir: Path,
    *,
    dry_run: bool = False,
    only: list[str] | None = None,
    reingest: bool = False,
) -> list[dict]:
    """Process .txt and .pdf files in a directory into the production DB."""
    files = sorted(
        [f for f in input_dir.iterdir() if f.suffix.lower() in (".txt", ".pdf")]
    )
    if only:
        only_set = set(only)
        files = [f for f in files if f.stem.split("_", 1)[0] in only_set or f.stem in only_set]
    print(f"Input: {input_dir}")
    print(f"DB:    {db_path}")
    print(f"Files: {len(files)} (.txt: {sum(1 for f in files if f.suffix == '.txt')}, .pdf: {sum(1 for f in files if f.suffix.lower() == '.pdf')})")

    if dry_run:
        for f in files:
            stem = f.stem
            novel_id = stem.split("_", 1)[0]
            title = stem.split("_", 1)[1] if "_" in stem else stem
            print(f"  [{novel_id}] {title} ({f.suffix})")
        print(f"\n--dry-run: {len(files)} files found, no data written.")
        return []

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    morph_cache: dict[tuple[str, str], str] = {}
    results = []
    for i, f in enumerate(files, 1):
        result = ingest_file(conn, f, morph_cache, reingest=reingest)
        if result.get("skipped"):
            print(f"  [{i}/{len(files)}] SKIP {result['novel_id']} {result['title']}")
        elif result.get("num_chapters"):
            print(
                f"  [{i}/{len(files)}] {result['novel_id']} {result['title']}"
                f" - {result['num_chapters']} chapters, {result['num_chunks']} chunks, {result['num_morpheme_types']} morphemes"
            )
        else:
            print(
                f"  [{i}/{len(files)}] {result['novel_id']} {result['title']}"
                f" - {result['num_chunks']} chunks, {result['num_morpheme_types']} morphemes"
            )
        results.append(result)

    conn.close()

    ingested_results = [r for r in results if not r.get("skipped")]
    skipped_results = [r for r in results if r.get("skipped")]

    print(f"\n{'=' * 50}")
    if ingested_results:
        print(f"Ingested ({len(ingested_results)}):")
        for r in ingested_results:
            if r.get("num_chapters"):
                print(f"  {r['novel_id']} {r['title']} ({r['num_chapters']} chapters, {r['num_chunks']} chunks)")
            else:
                print(f"  {r['novel_id']} {r['title']} ({r['num_chunks']} chunks)")
    if skipped_results:
        print(f"Skipped ({len(skipped_results)}):")
        for r in skipped_results:
            print(f"  {r['novel_id']} {r['title']}")
    print(f"{'=' * 50}")
    print(f"Done: {len(ingested_results)} ingested, {len(skipped_results)} skipped.")
    return results


def main() -> None:
    env_novels_dir = _env_path("NOVELS_DIR")
    env_db_path = _env_path("SQLITE_DB_PATH")

    parser = argparse.ArgumentParser(description="Ingest novel files into production local.db")
    parser.add_argument(
        "input_dir", type=Path, nargs="?", default=env_novels_dir,
        help="Directory containing {id}_{title}.txt files (default: NOVELS_DIR from .env)",
    )
    parser.add_argument(
        "--db", type=Path, default=env_db_path,
        help="Destination DB path (default: SQLITE_DB_PATH from .env)",
    )
    parser.add_argument("--dry-run", action="store_true", help="List files only, do not write")
    parser.add_argument(
        "--only", type=str, nargs="+", default=None,
        help="Only process files whose stem starts with these IDs (e.g. --only N7751GU N0668HS)",
    )
    parser.add_argument(
        "--files", type=Path, nargs="+", default=None,
        help="Process specific file paths (e.g. --files /path/to/N4941CW.pdf /path/to/12345_title.txt)",
    )
    parser.add_argument(
        "--files-from", type=Path, default=None,
        help="Read file paths from a text file (one path per line; blank lines and lines starting with # are ignored)",
    )
    parser.add_argument(
        "--reingest", action="store_true",
        help="Delete existing data and re-ingest from source file (CASCADE deletes chunks, embeddings, etc.)",
    )
    args = parser.parse_args()

    if args.files_from is not None:
        if not args.files_from.is_file():
            print(f"--files-from not found: {args.files_from}", file=sys.stderr)
            sys.exit(1)
        loaded: list[Path] = []
        for raw in args.files_from.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip().strip('"').strip("'")
            if not line or line.startswith("#"):
                continue
            loaded.append(Path(line))
        args.files = (args.files or []) + loaded

    if args.db is None:
        print("Error: --db not specified and SQLITE_DB_PATH not set in .env", file=sys.stderr)
        sys.exit(1)
    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    # --files mode: process explicit file paths
    if args.files:
        for f in args.files:
            if not f.exists():
                print(f"File not found: {f}", file=sys.stderr)
                sys.exit(1)
        ingest_files(args.db, args.files, dry_run=args.dry_run, reingest=args.reingest)
        return

    # Directory mode
    if args.input_dir is None:
        print("Error: input_dir not specified and NOVELS_DIR not set in .env", file=sys.stderr)
        sys.exit(1)
    if not args.input_dir.is_dir():
        print(f"Not a directory: {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    ingest_directory(args.db, args.input_dir, dry_run=args.dry_run, only=args.only, reingest=args.reingest)


if __name__ == "__main__":
    main()
