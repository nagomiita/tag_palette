"""tag_category_rules.csv をもとに SQLite の tags テーブルの category_id を更新する。

対象: category_id = 'general' のタグのみ。
ルールにマッチしたタグの category_id を上書きする。
"""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
from pathlib import Path

DB_DEFAULT = Path(r"C:\Users\taket\my_project\eagle\backend\local.db")
DATA_DIR = Path(__file__).parent / "src" / "tag_palette" / "data"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def load_rules(path: Path) -> list[dict]:
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


def match_rule(tag: str, rules: list[dict]) -> str | None:
    for rule in rules:
        mt = rule["match_type"]
        pat = rule["pattern"]
        if mt == "contains" and pat in tag:
            return rule["category"]
        if mt == "prefix" and tag.startswith(pat):
            return rule["category"]
        if mt == "suffix" and tag.endswith(pat):
            return rule["category"]
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="カテゴリルール適用 (SQLite UPDATE)")
    parser.add_argument("--db", type=Path, default=DB_DEFAULT, help="SQLite DB パス")
    parser.add_argument("--dry-run", action="store_true", help="実際に更新しない")
    args = parser.parse_args()

    if not args.db.exists():
        logger.error("DB が見つかりません: %s", args.db)
        return

    rules = load_rules(DATA_DIR / "tag_category_rules.csv")
    logger.info("ルール: %d 件", len(rules))

    conn = sqlite3.connect(str(args.db))

    # general タグを取得
    rows = conn.execute(
        "SELECT id, name FROM tags WHERE category_id = 'general'"
    ).fetchall()
    logger.info("general タグ: %d 件", len(rows))

    # マッチング
    updates: dict[str, list[tuple[str, str]]] = {}  # category -> [(tag_id, name)]
    for tag_id, name in rows:
        new_cat = match_rule(tag_id, rules)
        if new_cat:
            updates.setdefault(new_cat, []).append((tag_id, name or ""))

    total_updates = sum(len(v) for v in updates.values())
    logger.info("更新対象: %d 件", total_updates)

    # カテゴリ別サマリー
    for cat in sorted(updates, key=lambda c: len(updates[c]), reverse=True):
        logger.info("  %s: %d 件", cat, len(updates[cat]))

    if args.dry_run:
        logger.info("dry-run: 更新をスキップ")
        return

    if total_updates == 0:
        logger.info("更新対象なし")
        conn.close()
        return

    # UPDATE 実行
    updated = 0
    for cat, tag_list in updates.items():
        tag_ids = [t[0] for t in tag_list]
        # バッチで UPDATE (SQLite のパラメータ上限を考慮して 500 件ずつ)
        for i in range(0, len(tag_ids), 500):
            batch = tag_ids[i : i + 500]
            placeholders = ",".join("?" * len(batch))
            conn.execute(
                f"UPDATE tags SET category_id = ? WHERE id IN ({placeholders})",
                [cat, *batch],
            )
            updated += len(batch)

    conn.commit()
    conn.close()
    logger.info("完了: %d 件更新", updated)


if __name__ == "__main__":
    main()
