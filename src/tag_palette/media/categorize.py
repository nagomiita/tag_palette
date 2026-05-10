from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

CATEGORY_ID_TO_NAME = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta",
}

_csv_df = None


def _get_csv_df():
    global _csv_df
    if _csv_df is None:
        from tag_palette.shared.csv_reader import load_clean_tag_csv

        _csv_df = load_clean_tag_csv(require_ja=False)
    return _csv_df


def get_tag_category(tag_name: str) -> str | None:
    """
    タグをDanbooruカテゴリに分類する。

    Parameters:
        tag_name: 英語タグ名

    Returns:
        カテゴリ名 (general, artist, copyright, character, meta) または None。
    """
    csv_df = _get_csv_df()

    if tag_name not in csv_df.index:
        logger.debug("タグ '%s' はCSVに存在しません。スキップします。", tag_name)
        return None

    row = csv_df.loc[tag_name]
    category_id = row["category"]

    if category_id not in CATEGORY_ID_TO_NAME:
        logger.debug(
            "タグ '%s' のカテゴリID %s は無効です。スキップします。",
            tag_name,
            category_id,
        )
        return None

    return CATEGORY_ID_TO_NAME[category_id]
