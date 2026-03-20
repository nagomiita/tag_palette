"""
タグ CSV から説明文をローカル生成して CSV に書き出す。

Ollama は使わず、tags_json をもとに生成した description と confidence を組み立てる。
各カテゴリのタグを読点で区切って並べ、カテゴリ間を句点で区切るシンプルな形式。

Usage:
    uv run python infer_csv_descriptions.py \
        --input safe_media_tags.csv --output descriptions.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

# カテゴリの出力順
CATEGORY_ORDER = (
    "characters", "meta", "situation", "composition",
    "appearance", "costume", "pose", "emotion",
)

# ノイズタグ（除外対象）
NOISE_TAGS: frozenset[str] = frozenset({
    ":d", "> <", "^^", "><", "^ ^", "d:",
})

# ASCII のみのノイズパターン
ASCII_NOISE_RE = re.compile(r'^[\s:;^><=+\-_/\\|()[\]{}*.~0-9A-Za-z]+$')


def is_noise_tag(tag: str) -> bool:
    if tag in NOISE_TAGS:
        return True
    if len(tag) <= 2:
        return True
    if ASCII_NOISE_RE.fullmatch(tag):
        return True
    return False


# ヒントキーワード（カテゴリ再分類用）
APPEARANCE_HINTS = ("髪", "ヘア", "ツインテール", "ポニーテール", "三つ編み", "グラデ", "瞳", "目", "耳あて", "リボン", "花飾り", "帽", "足", "パンプス", "カラコン", "脚", "胸", "巨乳", "ほくろ", "へそ", "おさげ", "肌", "カール", "リボン", "シトの林")
COSTUME_HINTS = ("服", "シャツ", "スカート", "ズボン", "パンツ", "ショートパンツ", "ジャケット", "ベスト", "ニット", "コート", "パーカー", "ドレス", "制服", "ビキニ", "レオタード", "メイド", "エプロン", "ホワイトブラウン", "ニーソックス", "ソックス", "ストッキング", "チョーカー", "鎧", "ブーツ", "衣", "シンシン", "ヘアゴム", "手袋", "エポレット", "リボンタイ")
EMOTION_HINTS = ("赤面", "笑", "泣", "怒", "呆", "とろ", "困", "恥", "照", "エロ", "愁", "ハート")
POSE_HINTS = ("座", "立", "しゃがみ", "寝", "あぐら", "カメラ目線", "ピ", "手", "腕", "拳", "ザシキ", "振り上", "膝", "背", "横", "前")
SITUATION_HINTS = ("プール", "海", "ネ", "花", "夕日", "学校", "教室", "ベッド", "森", "ス", "ス", "部屋", "街", "学", "ガク", "ばら", "空", "雨", "雪")
COMPOSITION_HINTS = ("背景", "前景", "ぼかし", "構図", "全体", "上半身", "全身", "バストアップ", "マンガ", "コマ", "ジャンプ", "テ")


def unique_tags(tags: list[str], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        value = str(tag).strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
            if limit and len(result) >= limit:
                break
    return result


def clean_tags(tags: list[str], limit: int | None = None) -> list[str]:
    """重複・ノイズを除去し、上位 limit 件を返す。"""
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        value = str(tag).strip()
        if value and value not in seen and not is_noise_tag(value):
            seen.add(value)
            result.append(value)
            if limit and len(result) >= limit:
                break
    return result


def has_hint(tag: str, hints: tuple[str, ...]) -> bool:
    return any(h in tag for h in hints)


def reclassify_tags(raw_tags: dict[str, list[str]]) -> dict[str, list[str]]:
    """各カテゴリのタグをヒントベースで再分類する。"""
    normalized: dict[str, list[str]] = {}

    for cat in CATEGORY_ORDER:
        values = raw_tags.get(cat, [])
        for tag in unique_tags(values):
            # characters と meta はそのまま
            if cat in frozenset({"characters", "meta"}):
                normalized.setdefault(cat, []).append(tag)
                continue

            # ヒントベースで再分類
            target = cat
            if has_hint(tag, COSTUME_HINTS):
                target = "costume"
            elif has_hint(tag, EMOTION_HINTS):
                target = "emotion"
            elif has_hint(tag, POSE_HINTS):
                target = "pose"
            elif has_hint(tag, COMPOSITION_HINTS):
                target = "composition"
            elif has_hint(tag, SITUATION_HINTS):
                target = "situation"
            elif has_hint(tag, APPEARANCE_HINTS):
                target = "appearance"

            normalized.setdefault(target, []).append(tag)

    return normalized


def pick_subject(characters: list[str], meta: list[str]) -> str:
    chars = clean_tags(characters, 3)
    meta_set = set(meta)
    parts: list[str] = []

    for tag in chars:
        parts.append(tag)

    if not parts:
        if "女の子2人" in meta_set:
            parts.append("女の子2人")
        elif "男の子2人" in meta_set:
            parts.append("男の子2人")
        elif "ソロ" in meta_set:
            if "女の子" in meta_set:
                parts.append("女の子ソロ")
            elif "男の子" in meta_set:
                parts.append("男の子ソロ")
            else:
                parts.append("人物")
        elif frozenset({"男の子2人", "女の子", "女の子2人", "男の子", "ソロ"}) & meta_set:
            for tag in meta:
                if tag in frozenset({"男の子2人", "女の子", "女の子2人", "男の子", "ソロ"}):
                    parts.append(tag)
                    break

    return "、".join(parts) if parts else "人物"


# カテゴリごとのタグ上限
CATEGORY_LIMITS: dict[str, int] = {
    "characters": 3,
    "meta": 2,
    "situation": 4,
    "composition": 3,
    "appearance": 5,
    "costume": 5,
    "pose": 4,
    "emotion": 3,
}

CATEGORY_LABELS: dict[str, str] = {
    "characters": "キャラクター",
    "meta": "メタ",
    "situation": "状況",
    "composition": "構図",
    "appearance": "外見",
    "costume": "衣装",
    "pose": "ポーズ",
    "emotion": "表情",
}


def compose_description(raw_tags: dict[str, list[str]]) -> tuple[str, float]:
    """
    カテゴリ別タグから説明文と信頼度を生成する。

    Returns:
        (description, confidence) のタプル
    """
    tags = reclassify_tags(raw_tags)

    subject = pick_subject(
        tags.get("characters", []),
        tags.get("meta", []),
    )

    sections: list[str] = [subject]
    total_tags = 0
    covered_tags = 0

    for cat in CATEGORY_ORDER:
        if cat in frozenset({"characters", "meta"}):
            # characters/meta はカウントだけ（subjectで処理済み）
            raw = clean_tags(tags.get(cat, []))
            total_tags += len(raw)
            covered_tags += min(len(raw), CATEGORY_LIMITS.get(cat, 4))
            continue

        raw = clean_tags(tags.get(cat, []))
        total_tags += len(raw)
        limited = raw[:CATEGORY_LIMITS.get(cat, 4)]
        covered_tags += len(limited)

        if not limited:
            continue
        sections.append("、".join(limited))

    description = "。".join(sections)
    if not description.endswith("。"):
        description += "。"

    # 信頼度計算
    if total_tags > 0:
        coverage = covered_tags / total_tags
    else:
        coverage = 0.0

    filled = sum(1 for cat in CATEGORY_ORDER if clean_tags(tags.get(cat, [])))
    breadth_bonus = min(filled, 6) * 0.02
    confidence = min(0.95, round(0.4 + coverage * 0.4 + breadth_bonus, 2))

    return description, confidence


def main():
    """タグ CSV から説明文 CSV を生成"""
    parser = argparse.ArgumentParser(description="タグ CSV から説明文 CSV を生成")
    parser.add_argument("--input", type=Path, required=True, help="入力 CSV")
    parser.add_argument("--output", type=Path, required=True, help="出力 CSV")
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"入力 CSV が見つかりません: {args.input}")

    with open(args.input, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    extra_fields = ["description", "confidence", "response_json"]
    for field in extra_fields:
        if field not in fieldnames:
            fieldnames.append(field)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            raw_tags = json.loads(row.get("tags_json", "{}"))
            description, confidence = compose_description(raw_tags)
            row["description"] = description
            row["confidence"] = f"{confidence:.2f}"
            row["response_json"] = json.dumps(
                {"description": description, "confidence": confidence, "response_json": ""},
                ensure_ascii=False,
            )
            writer.writerow(row)

    print(f"完了: {len(rows)} 件 -> {args.output}")


if __name__ == "__main__":
    main()
