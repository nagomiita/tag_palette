import re

from db.models import Tag
from utils.csv_reader import load_clean_tag_csv
from utils.translations import get_translation_for_tag

# --- CSVの読み込みと前処理 ---
csv_df = load_clean_tag_csv(require_alias=False)


def get_genres(tag: Tag) -> list[tuple[str, str, str | None]]:
    """
    タグ名からジャンル名をすべて抽出し、日本語訳を優先的に返す。
    見つからなければ英語名を使用する。
    戻り値: [(ジャンルID, ジャンル名, 備考), ...]
    """
    results: list[tuple[str, str, str]] = []
    matches = re.findall(r"\((.*?)\)", tag.name)

    for value in reversed(matches):
        if value not in csv_df.index:
            print(f"⚠️ タグ '{tag.name}' の値 '{value}' はCSVに存在しません。")
            results.append((value, value, None))
            continue

        result = get_translation_for_tag(value, language="ja")
        if result is None:
            print(
                f"⚠️ タグ '{tag.name}' の値 '{value}' の日本語訳が見つかりませんでした。英語名 '{value}' を使用します。"
            )
            results.append((value, value, None))
        else:
            genre_name, note = result
            print(f"✅ タグ '{tag.name}' にジャンル '{genre_name}' を設定しました。")
            results.append((value, genre_name, note))

    if not results:
        print(f"ℹ️ タグ '{tag.name}' からジャンルを抽出できませんでした。")

    return results
