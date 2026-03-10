"""
Ollama (OpenAI互換API) 心理推定テストスクリプト

Usage:
    uv run python test_ollama.py <media_id>
    uv run python test_ollama.py  # ハードコードのサンプルデータで実行
"""

import argparse
import json
import sqlite3
from pathlib import Path

from openai import OpenAI

# =========================
# 設定
# =========================

DB_PATH = Path(r"C:\Users\taket\my_project\eagle\backend\local.db")
OLLAMA_URL = "http://localhost:11434/v1"
MODEL_NAME = "huihui_ai/qwen3.5-abliterated:27b"
TEMPERATURE = 0.8

# カテゴリ → input_data のキー
CATEGORY_KEY_MAP = {
    "pose": "pose",
    "emotion": "emotion",
    "appearance": "appearance",
    "background": "situation",
    "composition": "composition",
    "costume": "costume",
    "meta": "meta",
}


# =========================
# System Prompt
# =========================

SYSTEM_PROMPT = """
あなたはイラストの視覚情報からキャラクターの心理を推定するAIです。


入力として以下の情報が与えられます。
・ポーズ
・感情タグ
・外見タグ
・状況タグ
・構図タグ

これらを元にキャラクターの心理状態を自然に推定してください。

ルール:
・日本語のみ
・敬語は禁止
・自然な口語
・小説の地の文
・心理は推定として書く

必ず以下のJSON形式で出力してください。

{
  "emotion_summary": "",
  "state_summary": "",
  "inner_monologue": "",
  "confidence": 0.0
}
"""


# =========================
# DB からタグ取得
# =========================


def build_input_from_db(media_id: str) -> dict[str, list[str]]:
    """media_id から media_tags + tags を JOIN してカテゴリ別に分類する。"""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        """
        SELECT t.id, t.category_id, mt.confidence
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

    result: dict[str, list[str]] = {}
    for tag_id, category_id, _confidence in rows:
        key = CATEGORY_KEY_MAP.get(category_id or "general")
        if not key:
            continue
        result.setdefault(key, []).append(tag_id)

    return result


# =========================
# メイン
# =========================


def main() -> None:
    parser = argparse.ArgumentParser(description="Ollama 心理推定テスト")
    parser.add_argument("media_id", nargs="?", help="media テーブルの ID")
    args = parser.parse_args()

    if args.media_id:
        input_data = build_input_from_db(args.media_id)
        print(input_data)
        print(f"=== Media: {args.media_id} ===")
    else:
        input_data = {
            "pose": ["looking_down", "hands_on_own_chest"],
            "emotion": ["blush", "nervous"],
            "appearance": ["long_hair"],
            "situation": ["classroom"],
            "composition": ["upper_body"],
        }
        print("=== サンプルデータ ===")

    print(json.dumps(input_data, indent=2, ensure_ascii=False))

    # Ollama リクエスト
    client = OpenAI(base_url=OLLAMA_URL, api_key="ollama")
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)},
        ],
        extra_body={"options": {"think": False}},
    )
    content = response.choices[0].message.content

    print("\n=== Raw Response ===")
    print(content)

    # JSONパース試行
    try:
        result = json.loads(content)
        print("\n=== Parsed JSON ===")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print("\nJSONパース失敗")


if __name__ == "__main__":
    main()
