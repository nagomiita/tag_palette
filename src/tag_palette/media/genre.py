from __future__ import annotations

import importlib.resources
import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

_genre_df: pd.DataFrame | None = None


def _get_genre_df() -> pd.DataFrame:
    """genre.csv を読み込みキャッシュする。"""
    global _genre_df
    if _genre_df is None:
        data_ref = importlib.resources.files("tag_palette") / "data" / "genre.csv"
        with importlib.resources.as_file(data_ref) as csv_path:
            _genre_df = pd.read_csv(
                csv_path,
                encoding="utf-8",
                index_col="key",
                keep_default_na=False,
            )
    return _genre_df


def get_genres(tag_name: str) -> list[tuple[str, str, str | None]]:
    """
    タグ名の括弧からジャンル名をすべて抽出し、genre.csv から日本語訳を取得する。
    見つからなければ英語名を使用する。

    Parameters:
        tag_name: 英語タグ名 (例: "artoria_pendragon_(fate)")

    Returns:
        [(ジャンルID, ジャンル日本語名, None), ...] のリスト。
    """
    genre_df = _get_genre_df()
    results: list[tuple[str, str, str | None]] = []
    matches = re.findall(r"\((.*?)\)", tag_name)

    for value in reversed(matches):
        if value in genre_df.index:
            ja = str(genre_df.loc[value, "ja"]).strip()
            genre_name = ja if ja else value
            results.append((value, genre_name, None))
        else:
            logger.debug("ジャンル '%s' は genre.csv に存在しません。", value)
            results.append((value, value, None))

    if not results:
        logger.debug("タグ '%s' からジャンルを抽出できませんでした。", tag_name)

    return results
