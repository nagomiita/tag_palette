"""CSV マスタデータの読み込み。"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from .models import CategoryEntry, CategoryRule, DanbooruTag, GenreEntry

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_categories(path: Path | None = None) -> dict[str, CategoryEntry]:
    """category.csv → {id: CategoryEntry}"""
    path = path or DATA_DIR / "category.csv"
    result: dict[str, CategoryEntry] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cat_id = row["id"]
            result[cat_id] = CategoryEntry(id=cat_id, name=row.get("name", cat_id))
    logger.info("category.csv: %d 件", len(result))
    return result


def load_danbooru_tags(path: Path | None = None) -> dict[str, DanbooruTag]:
    """danbooru_tags.csv → {英語タグ名: DanbooruTag}"""
    path = path or DATA_DIR / "danbooru_tags.csv"
    result: dict[str, DanbooruTag] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tag = row["tag"]
            result[tag] = DanbooruTag(
                tag=tag,
                category=row.get("category", ""),
                count=int(row.get("count", 0)),
                genre=row.get("genre", "").strip(),
                ja=row.get("ja", "").strip(),
                memo=row.get("memo", ""),
            )
    logger.info("danbooru_tags.csv: %d 件", len(result))
    return result


def load_genres(path: Path | None = None) -> dict[str, GenreEntry]:
    """genre.csv → {key: GenreEntry}"""
    path = path or DATA_DIR / "genre.csv"
    result: dict[str, GenreEntry] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = row["key"]
            result[key] = GenreEntry(
                key=key,
                count=int(row.get("count", 0)),
                ja=row.get("ja", "").strip(),
            )
    logger.info("genre.csv: %d 件", len(result))
    return result


def load_category_rules(path: Path | None = None) -> list[CategoryRule]:
    """tag_category_rules.csv → [CategoryRule] (priority 降順)"""
    path = path or DATA_DIR / "tag_category_rules.csv"
    rules: list[CategoryRule] = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rules.append(
                CategoryRule(
                    match_type=row["match_type"],
                    pattern=row["pattern"],
                    category=row["category"],
                    priority=int(row.get("priority", 0)),
                )
            )
    rules.sort(key=lambda r: r.priority, reverse=True)
    logger.info("tag_category_rules.csv: %d 件", len(rules))
    return rules


def match_category_rule(tag: str, rules: list[CategoryRule]) -> str | None:
    """タグ名にマッチする最高優先度のルールのカテゴリを返す。マッチなしなら None。"""
    for rule in rules:
        if rule.match_type == "contains" and rule.pattern in tag:
            return rule.category
        if rule.match_type == "prefix" and tag.startswith(rule.pattern):
            return rule.category
        if rule.match_type == "suffix" and tag.endswith(rule.pattern):
            return rule.category
    return None


def load_translation_cache(path: Path | None = None) -> dict[str, str]:
    """translation_cache.csv (ヘッダなし en,ja) → {英語タグ名: 日本語名}"""
    path = path or DATA_DIR / "translation_cache.csv"
    result: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",", 1)
            if len(parts) == 2:
                result[parts[0]] = parts[1]
    logger.info("translation_cache.csv: %d 件", len(result))
    return result
