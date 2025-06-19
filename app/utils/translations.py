import re

from utils.csv_reader import load_clean_tag_csv


# --- 日本語判定関数 ---
def is_japanese(text: str) -> bool:
    """日本語（漢字・かな・カタカナのいずれか）を含むか"""
    return re.search(r"[\u3040-\u30FF\u4E00-\u9FFF]", text) is not None


def is_preferably_japanese(text: str) -> bool:
    """日本語っぽい（カタカナ・ひらがな）を含むか"""
    return re.search(r"[\u3040-\u30FF]", text) is not None


# --- CSVの読み込みと前処理 ---
csv_df = load_clean_tag_csv(require_alias=True)

# aliasカラムが空でないものだけに限定（NaNまたは空文字を除外）
csv_df = csv_df[csv_df["alias"].str.strip() != ""]


# --- DBのタグを走査して一致するCSVがあるものだけ処理 ---
def get_translation_for_tag(
    tag_name: str, language: str = "ja"
) -> tuple[str, str] | None:
    print(f"処理中: {tag_name}...")
    if tag_name not in csv_df.index:
        print("  - CSVに存在しないタグです。スキップします。")
        return

    row = csv_df.loc[tag_name]
    alias_text = row["alias"]
    alias_list = [a.strip() for a in alias_text.split(",") if a.strip()]
    if language != "ja":
        print(
            f"  - 日本語以外の言語({language})はまだサポートされていません。スキップします。"
        )
        return
    jp_candidates = [a for a in alias_list if is_japanese(a)]

    # --- 優先候補ロジック ---
    translated_name = None
    if jp_candidates:
        # ① 括弧を含み、かな・カナを含む（例: エンタープライズ(アズールレーン)）
        for cand in jp_candidates:
            if "(" in cand and is_preferably_japanese(cand):
                translated_name = cand
                break

        # ② カタカナ・ひらがなを含む候補
        if not translated_name:
            for cand in jp_candidates:
                if is_preferably_japanese(cand):
                    translated_name = cand
                    break

        # ③ 最初の候補
        if not translated_name:
            translated_name = jp_candidates[0]
    else:
        print("  - 日本語候補が見つかりません。")
        return

    print(f"  - 日本語候補: {translated_name}")
    note = alias_text

    # 翻訳登録
    return (translated_name, note)
