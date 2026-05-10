"""tag_palette.json のスキーマ定義。

FastAPI 等の Web アプリ側と共有するための Pydantic モデル。
このファイルは tag_palette の重い依存 (torch, imgutils 等) を一切 import しない。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 共通
# ---------------------------------------------------------------------------


class MediaType(str, Enum):
    IMAGE = "image"
    MANGA = "manga"
    VIDEO = "video"
    AUDIO = "audio"
    NOVEL = "novel"


# ---------------------------------------------------------------------------
# 画像 / 動画
# ---------------------------------------------------------------------------


class MediaPalette(BaseModel):
    """画像・動画の tag_palette.json スキーマ。"""

    id: str
    media_type: Literal["image", "manga", "video"] | None = None
    name: str
    thumbnail_name: str = ""
    ext: str

    # ジャンル
    genre: str | None = None

    # センシティブ判定
    is_sensitive: bool = False
    sensitive_method: str | None = None
    wd14_ratings: dict[str, float] | None = None
    anime_rating: dict[str, float] | None = None

    # スコア
    ai_score: float | None = None
    real_score: float | None = None
    monochrome_score: float | None = None
    classify_scores: dict[str, float] | None = None
    completeness_scores: dict[str, float] | None = None
    portrait_scores: dict[str, float] | None = None

    # タグ
    model_name: str = ""
    tags: dict[str, float] = Field(default_factory=dict)
    tags_ja: dict[str, str] = Field(default_factory=dict)

    # 漫画 OCR (media_type="manga" の場合)
    ocr_full_text: str | None = None
    num_panels: int | None = None
    num_texts: int | None = None
    panels: list[PanelSchema] | None = None
    texts: list[TextSchema] | None = None
    ratings: dict[str, float] | None = None

    generated_at: str = ""


class PanelSchema(BaseModel):
    """漫画のコマ情報。"""

    bbox: list[int]  # [x1, y1, x2, y2]


class TextSchema(BaseModel):
    """漫画のテキスト情報。"""

    bbox: list[int]  # [x1, y1, x2, y2]
    text: str = ""


# forward ref の解決
MediaPalette.model_rebuild()


# ---------------------------------------------------------------------------
# 音声
# ---------------------------------------------------------------------------


class AudioType(str, Enum):
    BGM = "bgm"
    SE = "se"
    VOICE = "voice"


class AudioPalette(BaseModel):
    """音声の tag_palette.json スキーマ。"""

    id: str
    media_type: Literal["audio"] = "audio"
    file_path: str = ""
    file_name: str = ""
    file_extension: str = ""

    audio_type: str  # "bgm" | "se" | "voice"
    duration_ms: int | None = None
    sample_rate: int | None = None
    file_size: int | None = None

    description: str | None = None
    transcript: str | None = None

    model_name: str = ""
    tags: dict[str, float] = Field(default_factory=dict)

    generated_at: str = ""


# ---------------------------------------------------------------------------
# 小説
# ---------------------------------------------------------------------------


class ChunkSchema(BaseModel):
    """小説のチャンク情報。"""

    seq: int = 0
    kind: str = "narrative"  # "dialogue" | "thought" | "narrative"
    body: str = ""


class NovelPalette(BaseModel):
    """小説の tag_palette.json スキーマ。"""

    id: str
    media_type: Literal["novel"] = "novel"
    title: str = ""
    author: str = ""
    url: str = ""

    tags: list[str] = Field(default_factory=list)  # ラベル名リスト
    is_sensitive: bool = False

    num_chunks: int = 0
    num_morphemes: int = 0
    chunks: list[ChunkSchema] = Field(default_factory=list)
    morphemes: dict[str, int] = Field(default_factory=dict)

    generated_at: str = ""


# ---------------------------------------------------------------------------
# ユニオン型 (判別用)
# ---------------------------------------------------------------------------


class TagPaletteFile(BaseModel):
    """tag_palette.json のルートスキーマ。

    media_type で判別して適切な型にパースする。
    """

    @staticmethod
    def parse_file_content(data: dict) -> MediaPalette | AudioPalette | NovelPalette:
        """dict から media_type に応じた適切なモデルを返す。"""
        media_type = data.get("media_type", "")
        if media_type == "audio":
            return AudioPalette.model_validate(data)
        if media_type == "novel":
            return NovelPalette.model_validate(data)
        return MediaPalette.model_validate(data)

    @staticmethod
    def parse_json_file(path: str) -> MediaPalette | AudioPalette | NovelPalette:
        """JSON ファイルパスから適切なモデルを返す。"""
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return TagPaletteFile.parse_file_content(data)
