"""データ構造定義。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TagPaletteEntry:
    """tag_palette.json 1件分 (画像/動画)。"""

    image_id: str
    image_name: str
    thumbnail_name: str
    ext: str
    model_name: str
    genre: str | None
    is_sensitive: bool
    ai_score: float | None
    real_score: float | None
    monochrome_score: float | None
    classify_scores: dict[str, float] | None
    completeness_scores: dict[str, float] | None
    portrait_scores: dict[str, float] | None
    tags: dict[str, float]  # {英語タグ: confidence}
    tags_ja: dict[str, str]  # {英語タグ: 日本語名}
    generated_at: str
    info_dir: Path
    tag_embedding: bytes | None  # embedding.npy から読み込んだ生バイト
    ccip_embedding: bytes | None  # ccip_embedding.npy から読み込んだ生バイト
    pose_embedding: bytes | None  # pose_embedding.npy から読み込んだ生バイト
    ocr_text: str | None  # 漫画OCRテキスト


@dataclass
class AudioPaletteEntry:
    """tag_palette.json 1件分 (音声)。"""

    asset_id: str
    file_path: str
    file_name: str
    file_extension: str
    audio_type: str  # "bgm", "se", "voice"
    duration_ms: int | None
    sample_rate: int | None
    file_size: int | None
    description: str | None
    transcript: str | None
    model_name: str
    tags: dict[str, float]
    generated_at: str


@dataclass
class NovelPaletteEntry:
    """tag_palette.json 1件分 (小説)。"""

    novel_id: str
    title: str
    author: str
    url: str
    tags: list[str]  # ラベル名のリスト
    is_sensitive: bool
    num_chunks: int
    num_morphemes: int
    chunks: list[dict]  # [{"seq": int, "kind": str, "body": str}, ...]
    generated_at: str


@dataclass
class DanbooruTag:
    """danbooru_tags.csv 1行分。"""

    tag: str
    category: str  # "0", "3", "4"
    count: int
    genre: str  # genre.csv の key
    ja: str
    memo: str


@dataclass
class CategoryEntry:
    """category.csv 1行分。"""

    id: str
    name: str


@dataclass
class GenreEntry:
    """genre.csv 1行分。"""

    key: str
    count: int
    ja: str


@dataclass
class CategoryRule:
    """tag_category_rules.csv 1行分。"""

    match_type: str  # "prefix", "suffix", "contains"
    pattern: str
    category: str  # category.csv の id
    priority: int
