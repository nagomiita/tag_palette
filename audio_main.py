"""音声ファイルのタグ生成スクリプト。

指定ディレクトリ内の音声ファイルをスキャンし、PANNs で分類タグを生成する。
BGM / SE / Voice は自動判定されるが、ディレクトリ名やオプションで上書き可能。

Usage:
    # 自動判定モード (デフォルト)
    uv run python audio_main.py --input-dir /path/to/audio

    # 種別を強制指定
    uv run python audio_main.py --input-dir /path/to/audio --type bgm

    # ディレクトリ名で判定 (bgm/, se/, voice/ など)
    # → 自動判定のフォールバックあり
    uv run python audio_main.py --input-dir /path/to/audio

    # 単一ファイル
    uv run python audio_main.py --input /path/to/file.mp3

    # SQLite に書き込み
    uv run python audio_main.py --input-dir /path/to/audio --db-path /path/to/db.sqlite3
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import sqlite3
import sys
import time

# Windows cp932 で出力できない文字を置換して出力する
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
from datetime import datetime, timezone
from pathlib import Path

from tag_palette.audio.labels_ja import get_japanese_description
from tag_palette.audio.tagger import (
    AudioTagResult,
    AudioType,
    detect_type_from_path,
    generate_audio_tags,
    is_audio_file,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 結果表示
# ---------------------------------------------------------------------------


def _print_result(audio_path: Path, result: AudioTagResult) -> None:
    """結果を見やすく表示する。"""
    print(f"\n{'='*60}")
    print(f"File: {audio_path.name}")
    print(f"Type: {result.audio_type.value.upper()}")
    print(f"Duration: {result.duration_ms}ms | SR: {result.sample_rate}Hz")
    print(f"Model: {result.model_name}")

    print(f"\nTags ({len(result.tags)}):")
    for tag, conf in result.tags.items():
        bar = "#" * int(conf * 40)
        print(f"  {conf:.3f} {bar} {tag}")

    if result.transcript:
        print(f"\nTranscript: {result.transcript}")


# ---------------------------------------------------------------------------
# JSON 出力
# ---------------------------------------------------------------------------


def _save_result_json(audio_path: Path, result: AudioTagResult, output_dir: Path | None = None) -> Path:
    """結果を JSON ファイルに保存する。"""
    out_dir = output_dir or audio_path.parent
    json_path = out_dir / f"{audio_path.stem}_audio_tags.json"

    data = {
        "file_name": audio_path.name,
        "file_path": str(audio_path),
        "audio_type": result.audio_type.value,
        "duration_ms": result.duration_ms,
        "sample_rate": result.sample_rate,
        "model_name": result.model_name,
        "tags": result.tags,
        "transcript": result.transcript,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return json_path


# ---------------------------------------------------------------------------
# SQLite 書き込み
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _import_to_sqlite(
    conn: sqlite3.Connection,
    audio_path: Path,
    result: AudioTagResult,
) -> None:
    """タグ付け結果を audio_assets テーブルに書き込む。"""
    now = _now_iso()
    file_path_str = str(audio_path.resolve())

    # UPSERT audio_assets
    conn.execute(
        """
        INSERT INTO audio_assets (id, file_path, file_name, file_extension,
                                  audio_type, duration_ms, sample_rate,
                                  description, file_size, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            audio_type = excluded.audio_type,
            duration_ms = excluded.duration_ms,
            sample_rate = excluded.sample_rate,
            description = excluded.description,
            file_size = excluded.file_size
        """,
        (
            audio_path.stem,  # id
            file_path_str,
            audio_path.name,
            audio_path.suffix.lstrip("."),
            result.audio_type.value,
            result.duration_ms,
            result.sample_rate,
            _build_description(result),
            audio_path.stat().st_size if audio_path.exists() else None,
            now,
        ),
    )
    conn.commit()


def _build_description(result: AudioTagResult) -> str:
    """タグとトランスクリプトから description テキストを構築する。"""
    parts = []
    # 上位タグをカンマ区切り
    top_tags = [tag for tag, conf in result.tags.items() if conf >= 0.1]
    if top_tags:
        parts.append(", ".join(top_tags))
    if result.transcript:
        parts.append(f"[transcript] {result.transcript}")
    return " | ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# ファイル探索
# ---------------------------------------------------------------------------


def find_audio_files(input_dir: Path) -> list[Path]:
    """ディレクトリ内の音声ファイルを再帰的に探索する。"""
    files: list[Path] = []
    for path in sorted(input_dir.rglob("*")):
        if path.is_file() and is_audio_file(path):
            files.append(path)
    return files


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="音声ファイルのタグ生成 (PANNs + Whisper)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--input", type=Path, help="単一の音声ファイルパス"
    )
    group.add_argument(
        "--input-dir", type=Path, help="音声ファイルを含むディレクトリ"
    )
    parser.add_argument(
        "--type",
        type=str,
        choices=["bgm", "se", "voice"],
        default=None,
        help="音声種別を強制指定 (省略時は自動判定、ディレクトリ名でも判定)",
    )
    parser.add_argument(
        "--db-path", type=Path, default=None,
        help="SQLite DB パス (指定時は DB にも書き込む)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="JSON 出力先ディレクトリ (省略時はファイルと同じ場所)",
    )
    parser.add_argument(
        "--top-k", type=int, default=20,
        help="返すタグの最大数 (デフォルト: 20)",
    )
    parser.add_argument(
        "--no-transcribe", action="store_true",
        help="Voice でも Whisper 文字起こしを行わない",
    )
    parser.add_argument(
        "--no-json", action="store_true",
        help="JSON ファイルを出力しない",
    )
    parser.add_argument(
        "--csv", type=Path, default=None,
        help="結果を CSV ファイルに出力するパス",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="結果の詳細表示を抑制",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # 強制指定
    type_override: AudioType | None = None
    if args.type:
        type_override = AudioType(args.type)

    # ファイルリスト構築
    if args.input:
        if not args.input.exists():
            logger.error("ファイルが見つかりません: %s", args.input)
            sys.exit(1)
        audio_files = [args.input]
    else:
        if not args.input_dir.is_dir():
            logger.error("ディレクトリが見つかりません: %s", args.input_dir)
            sys.exit(1)
        audio_files = find_audio_files(args.input_dir)

    if not audio_files:
        logger.info("対象の音声ファイルがありません。")
        return

    logger.info("対象ファイル数: %d", len(audio_files))

    # DB 接続 (オプション)
    conn: sqlite3.Connection | None = None
    if args.db_path:
        if not args.db_path.exists():
            logger.error("DB が見つかりません: %s", args.db_path)
            sys.exit(1)
        conn = sqlite3.connect(str(args.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

    # 出力ディレクトリ
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    # CSV 準備
    csv_file = None
    csv_writer = None
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        csv_file = open(args.csv, "w", encoding="utf-8", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow([
            "file_path", "file_name", "audio_type", "type_source",
            "duration_ms", "sample_rate",
            "description_ja",
            "tag_1", "conf_1", "tag_2", "conf_2", "tag_3", "conf_3",
            "tag_4", "conf_4", "tag_5", "conf_5",
            "transcript",
        ])

    # 処理
    start = time.perf_counter()
    processed = 0

    try:
        for i, audio_path in enumerate(audio_files, 1):
            logger.info("(%d/%d) %s", i, len(audio_files), audio_path.name)

            # 種別の決定: CLI引数 > ディレクトリ名 > 自動判定
            effective_override = type_override
            type_source = "auto"
            if effective_override is None:
                dir_type = detect_type_from_path(audio_path)
                if dir_type is not None:
                    effective_override = dir_type
                    type_source = "dir"
                    logger.info("  ディレクトリ名から種別を推定: %s", dir_type.value)
            else:
                type_source = "cli"

            try:
                result = generate_audio_tags(
                    audio_path,
                    audio_type_override=effective_override,
                    top_k=args.top_k,
                    transcribe_voice=not args.no_transcribe,
                )

                if not args.quiet:
                    _print_result(audio_path, result)

                if not args.no_json:
                    json_path = _save_result_json(audio_path, result, args.output_dir)
                    logger.info("  JSON 保存: %s", json_path.name)

                if conn is not None:
                    _import_to_sqlite(conn, audio_path, result)
                    logger.info("  DB 書き込み完了")

                # CSV 行書き込み
                if csv_writer is not None:
                    top_tags = list(result.tags.items())[:5]
                    tag_cols: list[str] = []
                    for tag, conf in top_tags:
                        tag_cols.extend([tag, f"{conf:.4f}"])
                    # 5件に満たない場合は空欄で埋める
                    while len(tag_cols) < 10:
                        tag_cols.extend(["", ""])
                    desc_ja = get_japanese_description(
                        result.tags, result.audio_type.value, result.transcript,
                    )
                    csv_writer.writerow([
                        str(audio_path),
                        audio_path.name,
                        result.audio_type.value,
                        type_source,
                        result.duration_ms,
                        result.sample_rate,
                        desc_ja,
                        *tag_cols,
                        result.transcript or "",
                    ])

                processed += 1

            except Exception as e:
                logger.error("処理失敗: %s -> %s", audio_path.name, e)

    finally:
        if conn is not None:
            conn.close()
        if csv_file is not None:
            csv_file.close()

    elapsed = time.perf_counter() - start
    logger.info(
        "\n完了: %d/%d 件 (%.2fs)",
        processed,
        len(audio_files),
        elapsed,
    )


if __name__ == "__main__":
    main()
