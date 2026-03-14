"""
Ollama 場面描写生成スクリプト

Usage:
    uv run python test_ollama.py <media_id>              # 単一メディアを処理
    uv run python test_ollama.py --all --limit 100       # 未処理を 100 件だけ処理
    uv run python test_ollama.py --all --concurrency 2   # 並列度を指定
    uv run python test_ollama.py                         # サンプルデータで実行
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ollama import AsyncClient, Client

from env_config import get_db_path

# =========================
# 設定
# =========================

DEFAULT_DB_PATH = Path(r"C:\Users\taket\my_project\eagle\backend\local.db")
DEFAULT_MODEL_NAME = "qwen3:14b"
DEFAULT_SENSITIVE_MODEL_NAME = "huihui_ai/qwen3.5-abliterated:9b"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_NUM_PREDICT = 500
DEFAULT_NUM_CTX = 2048
DEFAULT_KEEP_ALIVE = "15m"
DEFAULT_MIN_CONFIDENCE = 0.35
DEFAULT_MAX_TAGS_PER_CATEGORY = 6

# カテゴリ → input_data のキー
CATEGORY_KEY_MAP = {
    "pose": "pose",
    "emotion": "emotion",
    "appearance": "appearance",
    "background": "situation",
    "composition": "composition",
    "costume": "costume",
    "character": "characters",
    "meta": "meta",
}

DESCRIPTION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["description", "confidence"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class InferenceConfig:
    db_path: Path
    model_name: str
    sensitive_model_name: str
    temperature: float
    num_predict: int | None
    num_ctx: int | None
    keep_alive: str | None
    min_confidence: float | None
    max_tags_per_category: int | None


@dataclass(frozen=True)
class DescriptionResult:
    media_id: str
    is_sensitive: bool
    model: str
    description: str | None
    error: str | None
    elapsed: float


# =========================
# System Prompt
# =========================

SYSTEM_PROMPT = """
あなたはイラストのタグ情報から、そのイラストの場面を描写する文章を生成するAIです。

入力として以下のタグ情報がJSON形式で与えられます。
・ポーズ
・感情
・外見
・状況・背景
・構図
・衣装
・キャラクター名（判明している場合）

与えられたタグの情報を全て盛り込んで、イラストの場面を描写する文章を作成してください。

ルール:
・日本語のみ
・敬語は禁止
・自然な口語
・小説の地の文のように書く
・タグを羅列するのではなく、自然な文章にする
・出力は必ず JSON のみ

必ず以下のJSON形式で出力してください。

{
  "description": "場面描写の文章",
  "confidence": 0.0
}
"""


# =========================
# DB / 共通処理
# =========================


def resolve_db_path(cli_db_path: Path | None) -> Path:
    if cli_db_path is not None:
        return cli_db_path

    env_db_path = get_db_path()
    if env_db_path is not None:
        return env_db_path

    return DEFAULT_DB_PATH


def get_connection(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path), timeout=30)


def get_model_name(is_sensitive: bool, config: InferenceConfig) -> str:
    return config.sensitive_model_name if is_sensitive else config.model_name


def get_chat_options(config: InferenceConfig) -> dict[str, Any]:
    options: dict[str, Any] = {"temperature": config.temperature}
    if config.num_predict is not None:
        options["num_predict"] = config.num_predict
    if config.num_ctx is not None:
        options["num_ctx"] = config.num_ctx
    return options


def build_messages(input_data: dict[str, list[str]]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)},
    ]


def parse_response_content(content: str) -> tuple[str | None, str | None]:
    payload = content.strip()

    if payload.startswith("```"):
        lines = payload.splitlines()
        if len(lines) >= 3:
            payload = "\n".join(lines[1:-1]).strip()

    try:
        result = json.loads(payload)
    except json.JSONDecodeError:
        preview = content[:120].replace("\n", " ")
        return None, f"JSONパース失敗: {preview}"

    description = result.get("description")
    if not isinstance(description, str) or not description.strip():
        return None, "description が空です"

    return description.strip(), None


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def preview_text(text: str, limit: int = 80) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= limit else f"{text[:limit]}..."


# =========================
# DB からタグ取得
# =========================


def build_input_from_db(
    media_id: str,
    db_path: Path,
    *,
    is_sensitive: bool | None = None,
    min_confidence: float | None = None,
    max_tags_per_category: int | None = None,
) -> tuple[dict[str, list[str]], bool]:
    """media_id から media_tags + tags を JOIN してカテゴリ別に分類する。"""
    with get_connection(db_path) as conn:
        if is_sensitive is None:
            row = conn.execute(
                "SELECT is_sensitive FROM media WHERE id = ?",
                (media_id,),
            ).fetchone()
            is_sensitive = bool(row[0]) if row else False

        rows = conn.execute(
            """
            SELECT t.id, t.name, t.category_id, mt.confidence
            FROM media_tags mt
            JOIN tags t ON t.id = mt.tag_id
            WHERE mt.media_id = ?
            ORDER BY mt.confidence DESC
            """,
            (media_id,),
        ).fetchall()

    if not rows:
        raise ValueError(f"media_id '{media_id}' のタグが見つかりません")

    exclude_tags = {"mosaic_censoring"}
    result: dict[str, list[str]] = {}
    fallback_result: dict[str, list[str]] = {}
    for tag_id, tag_name, category_id, _confidence in rows:
        if tag_id in exclude_tags:
            continue
        key = CATEGORY_KEY_MAP.get(category_id or "general")
        if not key:
            continue
        tag_value = tag_name or tag_id

        fallback_tags = fallback_result.setdefault(key, [])
        if tag_value not in fallback_tags:
            if max_tags_per_category is None or len(fallback_tags) < max_tags_per_category:
                fallback_tags.append(tag_value)

        if min_confidence is not None and _confidence is not None and _confidence < min_confidence:
            continue

        tags = result.setdefault(key, [])
        if tag_value in tags:
            continue
        if max_tags_per_category is not None and len(tags) >= max_tags_per_category:
            continue
        tags.append(tag_value)

    if result:
        return result, is_sensitive
    if fallback_result:
        return fallback_result, is_sensitive

    raise ValueError(f"media_id '{media_id}' に有効なタグが見つかりません")


def save_description(db_path: Path, media_id: str, model: str, desc_text: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE media SET desc_text = ?, desc_model = ? WHERE id = ?",
            (desc_text, model, media_id),
        )
        conn.commit()


def get_pending_media_ids(
    db_path: Path,
    *,
    limit: int | None = None,
    start_after: str | None = None,
    only_sensitive: bool = False,
    only_safe: bool = False,
) -> list[tuple[str, bool]]:
    """desc_model が tag-based-v1 または desc_text が空の media を取得する。"""
    conditions = [
        "(m.desc_text IS NULL OR m.desc_text = '' OR m.desc_model = 'tag-based-v1')"
    ]
    params: list[Any] = []

    if only_sensitive:
        conditions.append("m.is_sensitive = 1")
    if only_safe:
        conditions.append("(m.is_sensitive = 0 OR m.is_sensitive IS NULL)")

    query = f"""
        SELECT m.id, m.is_sensitive
        FROM media m
        JOIN media_tags mt ON mt.media_id = m.id
        WHERE {" AND ".join(conditions)}
        GROUP BY m.id
        ORDER BY m.created_at, m.id
    """

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    pending = [(row[0], bool(row[1])) for row in rows]

    if start_after:
        start_index = next(
            (index for index, (media_id, _is_sensitive) in enumerate(pending) if media_id == start_after),
            None,
        )
        if start_index is None:
            raise ValueError(f"--start-after で指定した media_id が見つかりません: {start_after}")
        pending = pending[start_index + 1 :]

    if limit is not None:
        pending = pending[:limit]

    return pending


# =========================
# 推論
# =========================


def generate_description_sync(
    media_id: str,
    *,
    config: InferenceConfig,
    client: Client,
    save: bool = True,
) -> DescriptionResult:
    start = time.perf_counter()
    try:
        input_data, is_sensitive = build_input_from_db(
            media_id,
            config.db_path,
            min_confidence=config.min_confidence,
            max_tags_per_category=config.max_tags_per_category,
        )
        model = get_model_name(is_sensitive, config)
        response = client.chat(
            model=model,
            messages=build_messages(input_data),
            format=DESCRIPTION_RESPONSE_SCHEMA,
            options=get_chat_options(config),
            keep_alive=config.keep_alive,
            think=False,
        )
        description, error = parse_response_content(response.message.content)
        if error is not None:
            return DescriptionResult(
                media_id=media_id,
                is_sensitive=is_sensitive,
                model=model,
                description=None,
                error=error,
                elapsed=time.perf_counter() - start,
            )
        if save and description is not None:
            save_description(config.db_path, media_id, model, description)
        return DescriptionResult(
            media_id=media_id,
            is_sensitive=is_sensitive,
            model=model,
            description=description,
            error=None,
            elapsed=time.perf_counter() - start,
        )
    except Exception as exc:
        return DescriptionResult(
            media_id=media_id,
            is_sensitive=False,
            model=config.model_name,
            description=None,
            error=str(exc),
            elapsed=time.perf_counter() - start,
        )


async def generate_description_async(
    media_id: str,
    is_sensitive: bool,
    *,
    config: InferenceConfig,
    client: AsyncClient,
    save: bool = True,
) -> DescriptionResult:
    start = time.perf_counter()
    model = get_model_name(is_sensitive, config)

    try:
        input_data, _ = await asyncio.to_thread(
            build_input_from_db,
            media_id,
            config.db_path,
            is_sensitive=is_sensitive,
            min_confidence=config.min_confidence,
            max_tags_per_category=config.max_tags_per_category,
        )
        response = await client.chat(
            model=model,
            messages=build_messages(input_data),
            format=DESCRIPTION_RESPONSE_SCHEMA,
            options=get_chat_options(config),
            keep_alive=config.keep_alive,
            think=False,
        )
        description, error = parse_response_content(response.message.content)
        if error is not None:
            return DescriptionResult(
                media_id=media_id,
                is_sensitive=is_sensitive,
                model=model,
                description=None,
                error=error,
                elapsed=time.perf_counter() - start,
            )
        if save and description is not None:
            await asyncio.to_thread(save_description, config.db_path, media_id, model, description)
        return DescriptionResult(
            media_id=media_id,
            is_sensitive=is_sensitive,
            model=model,
            description=description,
            error=None,
            elapsed=time.perf_counter() - start,
        )
    except Exception as exc:
        return DescriptionResult(
            media_id=media_id,
            is_sensitive=is_sensitive,
            model=model,
            description=None,
            error=str(exc),
            elapsed=time.perf_counter() - start,
        )


def print_result(result: DescriptionResult, index: int, total: int) -> None:
    print(
        f"[{index}/{total}] {result.media_id} "
        f"(sensitive={result.is_sensitive}, model={result.model})"
    )
    if result.description:
        print(f"  OK ({result.elapsed:.1f}s): {preview_text(result.description)}")
    else:
        print(f"  SKIP ({result.elapsed:.1f}s): {result.error}")


async def run_batch_async(
    pending: list[tuple[str, bool]],
    *,
    config: InferenceConfig,
    save: bool,
    concurrency: int,
) -> None:
    total = len(pending)
    if total == 0:
        print("処理対象のメディアはありません")
        return

    print(
        f"=== バッチ処理開始: {total} 件 "
        f"(concurrency={concurrency}, save={save}) ===\n"
    )

    batch_start = time.perf_counter()
    success = 0
    fail = 0
    failed_ids: list[str] = []
    async_client = AsyncClient()
    pending_iter = iter(pending)
    in_flight: set[asyncio.Task[DescriptionResult]] = set()

    def submit_next() -> bool:
        try:
            media_id, is_sensitive = next(pending_iter)
        except StopIteration:
            return False
        task = asyncio.create_task(
            generate_description_async(
                media_id,
                is_sensitive,
                config=config,
                client=async_client,
                save=save,
            )
        )
        in_flight.add(task)
        return True

    for _ in range(min(concurrency, total)):
        submit_next()

    processed = 0
    while in_flight:
        done, still_running = await asyncio.wait(
            in_flight,
            return_when=asyncio.FIRST_COMPLETED,
        )
        in_flight = still_running

        for task in done:
            result = task.result()
            processed += 1
            print_result(result, processed, total)

            if result.description:
                success += 1
            else:
                fail += 1
                failed_ids.append(result.media_id)

            total_elapsed = time.perf_counter() - batch_start
            avg = total_elapsed / processed
            remaining = avg * (total - processed)
            print(
                "  進捗: "
                f"{processed}/{total} | "
                f"成功={success} | 失敗={fail} | "
                f"経過={format_duration(total_elapsed)} | "
                f"残り予測={format_duration(remaining)}\n"
            )

            submit_next()

    total_elapsed = time.perf_counter() - batch_start
    print(
        f"=== 完了: 成功={success}, 失敗={fail}, "
        f"合計時間={format_duration(total_elapsed)} ==="
    )
    if failed_ids:
        print(f"失敗IDサンプル: {', '.join(failed_ids[:10])}")


# =========================
# メイン
# =========================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ollama 場面描写生成")
    parser.add_argument("media_id", nargs="?", help="media テーブルの ID")
    parser.add_argument("--all", action="store_true", help="desc_text が空の全メディアを処理")
    parser.add_argument("--db", type=Path, help="SQLite DB パス (.env の SQLITE_DB_PATH を優先)")
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME, help="通常画像用モデル名")
    parser.add_argument(
        "--sensitive-model",
        default=DEFAULT_SENSITIVE_MODEL_NAME,
        help="センシティブ画像用モデル名",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f"temperature (default: {DEFAULT_TEMPERATURE})",
    )
    parser.add_argument(
        "--num-predict",
        type=int,
        default=DEFAULT_NUM_PREDICT,
        help=f"生成トークン上限 (default: {DEFAULT_NUM_PREDICT})",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=DEFAULT_NUM_CTX,
        help=f"コンテキスト長 (default: {DEFAULT_NUM_CTX})",
    )
    parser.add_argument(
        "--keep-alive",
        default=DEFAULT_KEEP_ALIVE,
        help=f"Ollama モデル保持時間 (default: {DEFAULT_KEEP_ALIVE})",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="同時実行数 (default: 1)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=DEFAULT_MIN_CONFIDENCE,
        help=f"この confidence 未満のタグは入力から除外 (default: {DEFAULT_MIN_CONFIDENCE})",
    )
    parser.add_argument(
        "--max-tags-per-category",
        type=int,
        default=DEFAULT_MAX_TAGS_PER_CATEGORY,
        help=(
            "カテゴリごとに送るタグ数の上限 "
            f"(default: {DEFAULT_MAX_TAGS_PER_CATEGORY})"
        ),
    )
    parser.add_argument("--limit", type=int, help="先頭から指定件数だけ処理")
    parser.add_argument("--start-after", help="この media_id の次から再開")
    parser.add_argument("--only-sensitive", action="store_true", help="センシティブのみ処理")
    parser.add_argument("--only-safe", action="store_true", help="非センシティブのみ処理")
    parser.add_argument("--dry-run", action="store_true", help="DB に保存しない")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.only_sensitive and args.only_safe:
        raise SystemExit("--only-sensitive と --only-safe は同時指定できません")
    if args.concurrency < 1:
        raise SystemExit("--concurrency は 1 以上を指定してください")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit は 1 以上を指定してください")
    if args.num_predict is not None and args.num_predict < 1:
        raise SystemExit("--num-predict は 1 以上を指定してください")
    if args.num_ctx is not None and args.num_ctx < 256:
        raise SystemExit("--num-ctx は 256 以上を指定してください")
    if args.min_confidence is not None and not 0 <= args.min_confidence <= 1:
        raise SystemExit("--min-confidence は 0 以上 1 以下を指定してください")
    if args.max_tags_per_category is not None and args.max_tags_per_category < 1:
        raise SystemExit("--max-tags-per-category は 1 以上を指定してください")


def build_config(args: argparse.Namespace) -> InferenceConfig:
    db_path = resolve_db_path(args.db)
    return InferenceConfig(
        db_path=db_path,
        model_name=args.model,
        sensitive_model_name=args.sensitive_model,
        temperature=args.temperature,
        num_predict=args.num_predict,
        num_ctx=args.num_ctx,
        keep_alive=args.keep_alive,
        min_confidence=args.min_confidence,
        max_tags_per_category=args.max_tags_per_category,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(args)
    config = build_config(args)
    save = not args.dry_run

    if not config.db_path.exists():
        raise SystemExit(f"DB が見つかりません: {config.db_path}")

    if args.all:
        pending = get_pending_media_ids(
            config.db_path,
            limit=args.limit,
            start_after=args.start_after,
            only_sensitive=args.only_sensitive,
            only_safe=args.only_safe,
        )
        asyncio.run(
            run_batch_async(
                pending,
                config=config,
                save=save,
                concurrency=args.concurrency,
            )
        )
        return

    if args.media_id:
        input_data, is_sensitive = build_input_from_db(
            args.media_id,
            config.db_path,
            min_confidence=config.min_confidence,
            max_tags_per_category=config.max_tags_per_category,
        )
        model = get_model_name(is_sensitive, config)
        print(f"=== Media: {args.media_id} (sensitive={is_sensitive}, model={model}) ===")
        print(json.dumps(input_data, indent=2, ensure_ascii=False))
        result = generate_description_sync(
            args.media_id,
            config=config,
            client=Client(),
            save=save,
        )
        if result.description:
            print(f"\n=== Description ===\n{result.description}")
            if save:
                print(f"\n=== DB Updated (media.id={args.media_id}) ===")
        else:
            print(f"\n=== Failed ===\n{result.error}")
        return

    input_data = {
        "pose": ["looking_down", "hands_on_own_chest"],
        "emotion": ["blush", "nervous"],
        "appearance": ["long_hair"],
        "situation": ["classroom"],
        "composition": ["upper_body"],
    }
    print("=== サンプルデータ ===")
    print(json.dumps(input_data, indent=2, ensure_ascii=False))
    response = Client().chat(
        model=config.model_name,
        messages=build_messages(input_data),
        format=DESCRIPTION_RESPONSE_SCHEMA,
        options=get_chat_options(config),
        keep_alive=config.keep_alive,
        think=False,
    )
    print(f"\n=== Response ===\n{response.message.content}")


if __name__ == "__main__":
    main()
