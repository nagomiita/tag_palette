from __future__ import annotations

import asyncio
import csv
import logging
import re
from pathlib import Path

from googletrans import Translator

logger = logging.getLogger(__name__)

_csv_df = None

# ── 翻訳キャッシュ ──────────────────────────────────────

_translation_cache: dict[str, str] = {}


def _default_cache_path() -> Path:
    """デフォルトのキャッシュファイルパスを返す (danbooru_tags.csv と同じディレクトリ)。"""
    import importlib.resources

    return Path(
        str(importlib.resources.files("tag_palette") / "data" / "translation_cache.csv")
    )


def load_translation_cache(cache_path: Path | None = None) -> None:
    """CSV から翻訳キャッシュを読み込む。"""
    path = cache_path or _default_cache_path()
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                _translation_cache[row[0]] = row[1]
    logger.info("翻訳キャッシュ読み込み: %d 件", len(_translation_cache))


def save_translation_cache(cache_path: Path | None = None) -> None:
    """翻訳キャッシュを CSV に保存する。"""
    path = cache_path or _default_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for tag, ja in sorted(_translation_cache.items()):
            writer.writerow([tag, ja])
    logger.info("翻訳キャッシュ保存: %d 件", len(_translation_cache))


def translate_tag(tag_name: str) -> str:
    """タグを日本語に翻訳する。

    解決順序: danbooru CSV → 翻訳キャッシュ → Google 翻訳 API → フォールバック
    """
    # 1. danbooru CSV から取得
    result = get_translation_for_tag(tag_name)
    if result:
        return result[0]

    # 2. キャッシュにあればそれを返す
    if tag_name in _translation_cache:
        return _translation_cache[tag_name]

    # 3. Google 翻訳 API で翻訳してキャッシュに保存
    readable = tag_name.replace("_", " ")
    try:
        ja = asyncio.run(text_translate(readable, src="en", dest="ja"))
        if ja:
            _translation_cache[tag_name] = ja
            return ja
    except Exception as e:
        logger.debug("Google翻訳失敗: %s -> %s", tag_name, e)

    # 4. フォールバック
    _translation_cache[tag_name] = readable
    return readable


def _get_csv_df():
    global _csv_df
    if _csv_df is None:
        from tag_palette._csv_reader import load_clean_tag_csv

        df = load_clean_tag_csv(require_alias=True)
        _csv_df = df[df["alias"].str.strip() != ""]
    return _csv_df


def is_japanese(text: str) -> bool:
    """日本語（漢字・かな・カタカナのいずれか）を含むか判定する。"""
    return re.search(r"[\u3040-\u30FF\u4E00-\u9FFF]", text) is not None


def is_preferably_japanese(text: str) -> bool:
    """日本語っぽい（カタカナ・ひらがな）を含むか判定する。"""
    return re.search(r"[\u3040-\u30FF]", text) is not None


def get_translation_for_tag(
    tag_name: str, language: str = "ja"
) -> tuple[str, str] | None:
    """
    CSVのalias情報からタグの日本語翻訳を取得する。

    Parameters:
        tag_name: 英語タグ名
        language: 言語コード (現在 "ja" のみサポート)

    Returns:
        (翻訳名, 備考) のタプル。見つからない場合は None。
    """
    csv_df = _get_csv_df()

    if tag_name not in csv_df.index:
        logger.debug("タグ '%s' はCSVに存在しません。スキップします。", tag_name)
        return None

    row = csv_df.loc[tag_name]
    alias_text = row["alias"]
    alias_list = [a.strip() for a in alias_text.split(",") if a.strip()]

    if language != "ja":
        logger.debug("日本語以外の言語(%s)はまだサポートされていません。", language)
        return None

    jp_candidates = [a for a in alias_list if is_japanese(a)]

    translated_name = None
    if jp_candidates:
        # 括弧を含み、かな・カナを含む候補を優先
        for cand in jp_candidates:
            if "(" in cand and is_preferably_japanese(cand):
                translated_name = cand
                break

        # カタカナ・ひらがなを含む候補
        if not translated_name:
            for cand in jp_candidates:
                if is_preferably_japanese(cand):
                    translated_name = cand
                    break

        # 最初の候補
        if not translated_name:
            translated_name = jp_candidates[0]
    else:
        logger.debug("タグ '%s' の日本語候補が見つかりません。", tag_name)
        return None

    logger.debug("タグ '%s' → 日本語候補: %s", tag_name, translated_name)
    note = alias_text

    return (translated_name, note)


_translator = Translator()


async def text_translate(text: str, src: str = "en", dest: str = "ja") -> str | None:
    """
    Google 翻訳 API でテキストを翻訳する (ネットワーク接続が必要)。

    Parameters:
        text: 翻訳対象テキスト
        src: 元言語コード
        dest: 翻訳先言語コード

    Returns:
        翻訳結果の文字列。
    """
    result = await _translator.translate(text, src=src, dest=dest)
    if result and result.text:
        return _clean_translation(result.text)
    raise ValueError("Translation returned None")


def _clean_translation(text: str) -> str:
    """翻訳結果の記号を正規化する。"""
    return (
        text.replace("\\", "")
        .replace("\u300c", "(")
        .replace("\u300d", ")")
        .replace("\uff08", "(")
        .replace("\uff09", ")")
    )
