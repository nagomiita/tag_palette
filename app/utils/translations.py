import re

from googletrans import Translator
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


translator = Translator()


async def text_translate(text: str, src: str = "en", dest: str = "ja") -> str | None:
    try:
        result = await translator.translate(text, src=src, dest=dest)
        if result and result.text:
            return _clean_translation(result.text)
        else:
            raise ValueError("Translation returned None")
    except Exception:
        raise


def _clean_translation(text: str) -> str:
    print(f"Before clean: {repr(text)}")  # ← 内部確認
    cleaned = (
        text.replace("\\", "")
        .replace("「", "(")
        .replace("」", ")")
        .replace("（", "(")
        .replace("）", ")")
    )
    print(f"After clean: {repr(cleaned)}")
    return cleaned


async def translate(self, tags: list[str]) -> dict[str, str]:
    translations = {}
    for tag in tags:
        try:
            genre_en = self.tags_repository.extract_genre(tag)
            if genre_en:
                genre_en = self._clean_translation(genre_en)
                genre_ja = self.tags_repository.get_genre(genre_en)
                if genre_ja:
                    translated_genre = genre_ja
                else:
                    print(f"Translating genre '{genre_en}' to Japanese...")
                    translated_genre = await self.safe_translate(
                        genre_en, src="en", dest="ja"
                    )
                    self.tags_repository.insert_genre(genre_en, translated_genre)
                    print(f"Translated genre '{genre_en}' to '{translated_genre}'")
                pos = tag.rfind("(")
                striped_tag = tag[:pos].strip() if pos != -1 else tag
                striped_tag = self._clean_translation(striped_tag)
                translated = await self.safe_translate(striped_tag, src="en", dest="ja")
                translated = f"{translated}({translated_genre})"
            else:
                translated = await self.safe_translate(tag, src="en", dest="ja")
            translations[tag] = self._clean_translation(translated)
            logger.info(f"Translated '{tag}' to '{translations[tag]}'")
            print(f"Translated '{tag}' to '{translations[tag]}'")
        except Exception as e:
            print(f"❌ Error translating '{tag}': {e}")
            raise
    return translations
