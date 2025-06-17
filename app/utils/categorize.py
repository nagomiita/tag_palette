from db.models import Tag
from utils.csv_reader import load_clean_tag_csv

CATEGORY_ID_TO_NAME = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta",
}

# --- CSVの読み込みと前処理 ---
csv_df = load_clean_tag_csv(require_alias=False)


def get_tag_category(tag: Tag) -> str | None:
    """
    タグをカテゴリに分類し、データベースに保存する。
    """
    if tag.name not in csv_df.index:
        print(f"タグ {tag.name} はCSVに存在しません。スキップします。")
        return

    row = csv_df.loc[tag.name]
    category_id = row["category"]
    if category_id not in CATEGORY_ID_TO_NAME:
        print(
            f"タグ {tag.name} のカテゴリID {category_id} は無効です。スキップします。"
        )
        return

    category_name = CATEGORY_ID_TO_NAME[category_id]
    print(f"タグ {tag.name} をカテゴリ '{category_name}' に分類しました。")
    return category_name
