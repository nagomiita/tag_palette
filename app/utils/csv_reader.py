from pathlib import Path

import pandas as pd


def load_clean_tag_csv(require_alias: bool = True) -> pd.DataFrame:
    """
    タグCSVを読み込み、必要に応じてaliasが空の行を除外する。

    Parameters:
        require_alias (bool): True の場合、alias が空の行は除外される

    Returns:
        pd.DataFrame: 前処理されたDataFrame（インデックスは 'tag'）
    """
    df = pd.read_csv(
        Path("./models/danbooru_tags.csv"),
        encoding="utf-8",
        index_col="tag",
        keep_default_na=False,
    )

    if require_alias:
        df = df[df["alias"].str.strip() != ""]

    return df
