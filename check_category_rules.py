"""SQLite の tags テーブルで category_id=general のタグに対し、
tag_category_rules.csv でどこまでカテゴライズできるか検証する。

media_tags の使用回数も集計し、実際に使われているタグの優先度を可視化する。
"""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
from collections import Counter
from pathlib import Path

DB_DEFAULT = Path(r"C:\Users\taket\my_project\eagle\backend\local.db")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "src" / "tag_palette" / "data"


def load_rules(path: Path) -> list[dict]:
    """tag_category_rules.csv → [{match_type, pattern, category, priority}]"""
    rules = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rules.append({
                "match_type": row["match_type"],
                "pattern": row["pattern"],
                "category": row["category"],
                "priority": int(row.get("priority", 0)),
            })
    rules.sort(key=lambda r: r["priority"], reverse=True)
    return rules


def match_rule(tag: str, rules: list[dict]) -> dict | None:
    """最高優先度でマッチするルールを返す。"""
    for rule in rules:
        mt = rule["match_type"]
        pat = rule["pattern"]
        if mt == "contains" and pat in tag:
            return rule
        if mt == "prefix" and tag.startswith(pat):
            return rule
        if mt == "suffix" and tag.endswith(pat):
            return rule
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="カテゴリルール検証 (SQLite)")
    parser.add_argument(
        "--db", type=Path, default=DB_DEFAULT,
        help="SQLite データベースパス (env: SQLITE_DB_PATH)",
    )
    parser.add_argument(
        "--top-unmatched", type=int, default=50,
        help="マッチしなかったタグの表示件数 (使用回数順, default: 50)",
    )
    parser.add_argument(
        "--samples", type=int, default=10,
        help="カテゴリ別マッチサンプル件数 (default: 10)",
    )
    args = parser.parse_args()

    if not args.db or not args.db.exists():
        logger.error("DB が見つかりません: %s", args.db)
        return

    rules = load_rules(DATA_DIR / "tag_category_rules.csv")
    logger.info("ルール: %d 件", len(rules))

    conn = sqlite3.connect(str(args.db))

    # general カテゴリのタグを取得 (id=英語名, name=日本語名)
    # media_tags との JOIN で使用回数も取得
    rows = conn.execute("""
        SELECT t.id, t.name, COUNT(mt.media_id) AS usage_count
        FROM tags t
        LEFT JOIN media_tags mt ON mt.tag_id = t.id
        WHERE t.category_id = 'general'
        GROUP BY t.id, t.name
        ORDER BY usage_count DESC
    """).fetchall()
    conn.close()

    logger.info("general タグ (SQLite): %d 件", len(rows))

    # (tag_id, name, usage_count)
    matched_by_cat: dict[str, list[tuple[str, str, int, str]]] = {}
    unmatched: list[tuple[str, str, int]] = []

    for tag_id, name, usage_count in rows:
        rule = match_rule(tag_id, rules)
        if rule:
            cat = rule["category"]
            matched_by_cat.setdefault(cat, []).append((tag_id, name or "", usage_count, rule["pattern"]))
        else:
            unmatched.append((tag_id, name or "", usage_count))

    total = len(rows)
    total_matched = total - len(unmatched)

    # サマリー
    print()
    print("=" * 60)
    print(f"general タグ総数 (SQLite): {total}")
    print(f"マッチ: {total_matched} ({total_matched / total * 100:.1f}%)")
    print(f"未マッチ: {len(unmatched)} ({len(unmatched) / total * 100:.1f}%)")
    print("=" * 60)

    # カテゴリ別集計
    print()
    print("--- カテゴリ別マッチ件数 ---")
    for cat in sorted(matched_by_cat, key=lambda c: len(matched_by_cat[c]), reverse=True):
        tags_list = matched_by_cat[cat]
        total_usage = sum(t[2] for t in tags_list)
        print(f"  {cat:15s}: {len(tags_list):5d} 件  (使用計: {total_usage:>7d})")

    # カテゴリ別サンプル
    if args.samples > 0:
        print()
        print("--- カテゴリ別マッチサンプル ---")
        for cat in sorted(matched_by_cat, key=lambda c: len(matched_by_cat[c]), reverse=True):
            tags_list = matched_by_cat[cat]
            samples = sorted(tags_list, key=lambda t: t[2], reverse=True)[:args.samples]
            print(f"\n  [{cat}] ({len(tags_list)} 件)")
            for tag_id, name, usage, pattern in samples:
                name_display = f" ({name})" if name and name != tag_id else ""
                print(f"    {tag_id:40s}{name_display:20s}  usage={usage:>5d}  pattern={pattern}")

    # パターン別ヒット数
    print()
    print("--- パターン別ヒット数 ---")
    pattern_counter: Counter[str] = Counter()
    for tags_list in matched_by_cat.values():
        for _, _, _, pattern in tags_list:
            pattern_counter[pattern] += 1
    for pattern, cnt in pattern_counter.most_common(30):
        print(f"  {pattern:30s}: {cnt:5d} 件")

    # 未マッチ (使用回数降順)
    if args.top_unmatched > 0:
        print()
        print(f"--- 未マッチ上位 {args.top_unmatched} 件 (使用回数順) ---")
        for tag_id, name, usage in unmatched[:args.top_unmatched]:
            name_display = f" ({name})" if name and name != tag_id else ""
            print(f"  {tag_id:40s}{name_display:20s}  usage={usage:>5d}")


if __name__ == "__main__":
    main()
