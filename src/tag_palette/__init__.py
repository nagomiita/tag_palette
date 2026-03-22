"""tag-palette: WD14 Tagger を使った画像タグ生成ライブラリ。"""

from tag_palette.categorize import CATEGORY_ID_TO_NAME, get_tag_category
from tag_palette.embedding import (
    base64_to_embedding,
    embedding_to_base64,
    load_tag_embeddings,
    save_tag_embeddings,
    tags_to_embedding,
)
from tag_palette.genre import get_genres
from tag_palette.sensitive import (
    detect_sensitive,
    get_anime_rating,
    is_sensitive_by_anime_rating,
    is_sensitive_by_ratings,
)
from tag_palette.tagger import TagResult, generate_tags, generate_tags_batch
from tag_palette.translations import (
    get_translation_for_tag,
    is_japanese,
    is_preferably_japanese,
    load_translation_cache,
    save_translation_cache,
    text_translate,
    translate_tag,
    translate_tags,
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
    "translate_tags",
    "load_translation_cache",
    "save_translation_cache",
    "is_japanese",
    "is_preferably_japanese",
    # Categorization
    "CATEGORY_ID_TO_NAME",
    "get_tag_category",
    # Genre
    "get_genres",
    # Embedding
    "tags_to_embedding",
    "embedding_to_base64",
    "base64_to_embedding",
    "load_tag_embeddings",
    "save_tag_embeddings",
    # Sensitive content
    "is_sensitive_by_ratings",
    "is_sensitive_by_anime_rating",
    "get_anime_rating",
    "detect_sensitive",
]
