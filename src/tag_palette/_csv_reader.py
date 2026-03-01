from __future__ import annotations

import importlib.resources

import pandas as pd


def load_clean_tag_csv(require_alias: bool = True) -> pd.DataFrame:
    """
    タグCSVを読み込み、必要に応じてaliasが空の行を除外する。

    Parameters:
        require_alias (bool): True の場合、alias が空の行は除外される

    Returns:
        pd.DataFrame: 前処理されたDataFrame（インデックスは 'tag'）
    """
    data_ref = importlib.resources.files("tag_palette") / "data" / "danbooru_tags.csv"
    with importlib.resources.as_file(data_ref) as csv_path:
        df = pd.read_csv(
            csv_path,
            encoding="utf-8",
            index_col="tag",
            keep_default_na=False,
        )

    if require_alias:
        df = df[df["alias"].str.strip() != ""]

    return df
