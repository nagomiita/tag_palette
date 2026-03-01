from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_csv_df = None


def _get_csv_df():
    global _csv_df
    if _csv_df is None:
        from tag_palette._csv_reader import load_clean_tag_csv

        _csv_df = load_clean_tag_csv(require_alias=False)
    return _csv_df


def get_genres(tag_name: str) -> list[tuple[str, str, str | None]]:
    """
    タグ名からジャンル名をすべて抽出し、日本語訳を優先的に返す。
    見つからなければ英語名を使用する。

    Parameters:
        tag_name: 英語タグ名 (例: "artoria_pendragon_(fate)")

    Returns:
        [(ジャンルID, ジャンル名, 備考), ...] のリスト。
    """
    from tag_palette.translations import get_translation_for_tag

    csv_df = _get_csv_df()
    results: list[tuple[str, str, str | None]] = []
    matches = re.findall(r"\((.*?)\)", tag_name)

    for value in reversed(matches):
        if value not in csv_df.index:
            logger.debug("タグ '%s' の値 '%s' はCSVに存在しません。", tag_name, value)
            results.append((value, value, None))
            continue

        result = get_translation_for_tag(value, language="ja")
        if result is None:
            logger.debug(
                "タグ '%s' の値 '%s' の日本語訳が見つかりませんでした。",
                tag_name,
                value,
            )
            results.append((value, value, None))
        else:
            genre_name, note = result
            logger.debug("タグ '%s' にジャンル '%s' を設定しました。", tag_name, genre_name)
            results.append((value, genre_name, note))

    if not results:
        logger.debug("タグ '%s' からジャンルを抽出できませんでした。", tag_name)

    return results
