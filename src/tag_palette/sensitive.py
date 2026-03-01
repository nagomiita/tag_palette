from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_sensitive_tags: frozenset[str] | None = None


def _default_csv_path() -> Path:
    import importlib.resources

    return Path(
        str(importlib.resources.files("tag_palette") / "data" / "sensitive_tags.csv")
    )


def load_sensitive_tags(csv_path: Path | None = None) -> None:
    """sensitive_tags.csv からセンシティブタグ一覧を読み込む。"""
    global _sensitive_tags
    path = csv_path or _default_csv_path()
    if not path.exists():
        logger.warning("sensitive_tags.csv が見つかりません: %s", path)
        _sensitive_tags = frozenset()
        return

    tags: set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            tag = line.strip()
            if tag:
                tags.add(tag)

    _sensitive_tags = frozenset(tags)
    logger.info("センシティブタグ読み込み: %d 件", len(_sensitive_tags))


def save_sensitive_tags(csv_path: Path | None = None) -> None:
    """現在のセンシティブタグ一覧を CSV に保存する。"""
    path = csv_path or _default_csv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tags = _sensitive_tags or frozenset()
    with open(path, "w", encoding="utf-8") as f:
        for tag in sorted(tags):
            f.write(tag + "\n")
    logger.info("センシティブタグ保存: %d 件", len(tags))


def add_sensitive_tag(tag_name: str) -> None:
    """センシティブタグを追加する。"""
    global _sensitive_tags
    if _sensitive_tags is None:
        load_sensitive_tags()
    _sensitive_tags = _sensitive_tags | frozenset({tag_name.lower()})


def remove_sensitive_tag(tag_name: str) -> None:
    """センシティブタグを削除する。"""
    global _sensitive_tags
    if _sensitive_tags is None:
        load_sensitive_tags()
    _sensitive_tags = _sensitive_tags - frozenset({tag_name.lower()})


def is_sensitive(tag_name: str) -> bool:
    """タグ名がセンシティブタグに該当するか判定する。"""
    global _sensitive_tags
    if _sensitive_tags is None:
        load_sensitive_tags()
    return tag_name.lower() in _sensitive_tags
