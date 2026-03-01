"""tag-palette: WD14 Tagger を使った画像タグ生成ライブラリ。"""

from tag_palette.categorize import CATEGORY_ID_TO_NAME, get_tag_category
from tag_palette.genre import get_genres
from tag_palette.sensitive import SENSITIVE_KEYWORDS, is_sensitive
from tag_palette.tagger import TagResult, generate_tags, generate_tags_batch
from tag_palette.translations import (
    get_translation_for_tag,
    is_japanese,
    is_preferably_japanese,
    load_translation_cache,
    save_translation_cache,
    text_translate,
    translate_tag,
)

__all__ = [
    # Core tagging
    "TagResult",
    "generate_tags",
    "generate_tags_batch",
    # Translation
    "get_translation_for_tag",
    "text_translate",
    "translate_tag",
    "load_translation_cache",
    "save_translation_cache",
    "is_japanese",
    "is_preferably_japanese",
    # Categorization
    "CATEGORY_ID_TO_NAME",
    "get_tag_category",
    # Genre
    "get_genres",
    # Sensitive content
    "SENSITIVE_KEYWORDS",
    "is_sensitive",
]
