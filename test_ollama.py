"""
Ollama 場面描写生成スクリプト

Usage:
    uv run python test_ollama.py <media_id>   # 単一メディアを処理
    uv run python test_ollama.py --all         # desc_text が空の全メディアを処理
    uv run python test_ollama.py               # サンプルデータで実行
"""

import argparse
import json
import sqlite3
import time
from pathlib import Path

from ollama import chat

# =========================
# 設定
# =========================

DB_PATH = Path(r"C:\Users\taket\my_project\eagle\backend\local.db")
MODEL_NAME = "qwen3:14b"
MODEL_NAME_FOR_SENSITIVE = "huihui_ai/qwen3.5-abliterated:9b"
TEMPERATURE = 0.2

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

必ず以下のJSON形式で出力してください。

{
  "description": "場面描写の文章",
  "confidence": 0.0
}
"""


# =========================
# DB からタグ取得
# =========================


def build_input_from_db(media_id: str) -> tuple[dict[str, list[str]], bool]:
    """media_id から media_tags + tags を JOIN してカテゴリ別に分類する。
    Returns: (タグ辞書, is_sensitive)
    """
    conn = sqlite3.connect(str(DB_PATH))

    # is_sensitive を取得
    row = conn.execute(
        "SELECT is_sensitive FROM media WHERE id = ?", (media_id,)
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
    conn.close()

    if not rows:
        raise ValueError(f"media_id '{media_id}' のタグが見つかりません")

    EXCLUDE_TAGS = {"mosaic_censoring"}

    result: dict[str, list[str]] = {}
    for tag_id, tag_name, category_id, _confidence in rows:
        if tag_id in EXCLUDE_TAGS:
            continue
        key = CATEGORY_KEY_MAP.get(category_id or "general")
        if not key:
            continue
        result.setdefault(key, []).append(tag_name or tag_id)

    return result, is_sensitive


# =========================
# 推論 & 保存
# =========================


def generate_description(media_id: str, *, save: bool = True) -> str | None:
    """1件のメディアに対して推論し、結果を返す。save=True なら DB にも保存する。"""
    input_data, is_sensitive = build_input_from_db(media_id)
    model = MODEL_NAME_FOR_SENSITIVE if is_sensitive else MODEL_NAME

    response = chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)},
        ],
        options={"temperature": TEMPERATURE},
        think=False,
    )
    content = response.message.content

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        print(f"  JSONパース失敗: {content[:100]}")
        return None

    desc_text = result.get("description", "")

    if save and desc_text:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "UPDATE media SET desc_text = ?, desc_model = ? WHERE id = ?",
            (desc_text, model, media_id),
        )
        conn.commit()
        conn.close()

    return desc_text


def get_pending_media_ids() -> list[tuple[str, bool]]:
    """desc_text が空の media_id と is_sensitive を取得する。"""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        """
        SELECT m.id, m.is_sensitive
        FROM media m
        JOIN media_tags mt ON mt.media_id = m.id
        WHERE m.desc_text IS NULL OR m.desc_text = ''
        GROUP BY m.id
        ORDER BY m.created_at
        """
    ).fetchall()
    conn.close()
    return [(row[0], bool(row[1])) for row in rows]


def run_batch() -> None:
    """desc_text が空の全メディアを一括処理する。"""
    pending = get_pending_media_ids()
    total = len(pending)
    if total == 0:
        print("処理対象のメディアはありません")
        return

    print(f"=== バッチ処理開始: {total} 件 ===\n")
    batch_start = time.time()
    success = 0
    fail = 0

    for i, (media_id, is_sensitive) in enumerate(pending, 1):
        item_start = time.time()
        model = MODEL_NAME_FOR_SENSITIVE if is_sensitive else MODEL_NAME
        print(f"[{i}/{total}] {media_id} (sensitive={is_sensitive}, model={model})")

        try:
            desc = generate_description(media_id, save=True)
            elapsed = time.time() - item_start
            if desc:
                print(f"  OK ({elapsed:.1f}s): {desc[:80]}...")
                success += 1
            else:
                print(f"  SKIP ({elapsed:.1f}s): パース失敗")
                fail += 1
        except Exception as e:
            elapsed = time.time() - item_start
            print(f"  ERROR ({elapsed:.1f}s): {e}")
            fail += 1

        # 進捗サマリ
        total_elapsed = time.time() - batch_start
        avg = total_elapsed / i
        remaining = avg * (total - i)
        print(f"  進捗: {i}/{total} | 経過: {total_elapsed:.0f}s | 残り予測: {remaining:.0f}s\n")

    total_elapsed = time.time() - batch_start
    print(f"=== 完了: 成功={success}, 失敗={fail}, 合計時間={total_elapsed:.0f}s ===")


# =========================
# メイン
# =========================


def main() -> None:
    parser = argparse.ArgumentParser(description="Ollama 場面描写生成")
    parser.add_argument("media_id", nargs="?", help="media テーブルの ID")
    parser.add_argument("--all", action="store_true", help="desc_text が空の全メディアを処理")
    args = parser.parse_args()

    # --all: バッチ処理
    if args.all:
        run_batch()
        return

    # 単一 media_id
    if args.media_id:
        input_data, is_sensitive = build_input_from_db(args.media_id)
        model = MODEL_NAME_FOR_SENSITIVE if is_sensitive else MODEL_NAME
        print(f"=== Media: {args.media_id} (sensitive={is_sensitive}, model={model}) ===")
        print(json.dumps(input_data, indent=2, ensure_ascii=False))
        desc = generate_description(args.media_id, save=True)
        if desc:
            print(f"\n=== Description ===\n{desc}")
            print(f"\n=== DB Updated (media.id={args.media_id}) ===")
        return

    # サンプルデータ
    input_data = {
        "pose": ["looking_down", "hands_on_own_chest"],
        "emotion": ["blush", "nervous"],
        "appearance": ["long_hair"],
        "situation": ["classroom"],
        "composition": ["upper_body"],
    }
    print("=== サンプルデータ ===")
    print(json.dumps(input_data, indent=2, ensure_ascii=False))
    response = chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)},
        ],
        options={"temperature": TEMPERATURE},
        think=False,
    )
    print(f"\n=== Response ===\n{response.message.content}")


if __name__ == "__main__":
    main()
