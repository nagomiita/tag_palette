"""漫画ページ解析モジュール。

OpenCV でパネル（コマ）検出を行い、NDLOCR-Lite で日本語テキストを認識する。
各パネルは WD14 でタグ付けできるよう切り出して返す。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# データ構造
# ---------------------------------------------------------------------------


@dataclass
class PanelInfo:
    """検出された1コマの情報。"""

    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    tags: dict[str, float] = field(default_factory=dict)
    tags_ja: dict[str, str] = field(default_factory=dict)


@dataclass
class TextInfo:
    """検出された1テキスト領域の情報。"""

    bbox: tuple[int, int, int, int]
    text: str = ""


@dataclass
class MangaPageResult:
    """漫画1ページの解析結果。"""

    panels: list[PanelInfo] = field(default_factory=list)
    texts: list[TextInfo] = field(default_factory=list)
    ocr_full_text: str = ""  # 全セリフを結合したテキスト


# ---------------------------------------------------------------------------
# OpenCV パネル検出
# ---------------------------------------------------------------------------


def _detect_panels(
    image: np.ndarray,
    *,
    min_panel_ratio: float = 0.02,
    max_panel_ratio: float = 0.9,
    border_margin: int = 5,
) -> list[tuple[int, int, int, int]]:
    """OpenCV でコマ割りを検出する。

    白い枠線で区切られた漫画のコマを輪郭検出で抽出する。

    Parameters:
        image: BGR 画像 (OpenCV 形式)
        min_panel_ratio: ページ面積に対する最小パネル比率
        max_panel_ratio: ページ面積に対する最大パネル比率
        border_margin: 画像端のマージン (px)

    Returns:
        [(x1, y1, x2, y2), ...] のリスト。上→下、左→右の読み順でソート。
    """
    h, w = image.shape[:2]
    page_area = h * w

    # グレースケール化
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 二値化 (白い枠線を検出するため反転二値化)
    _, binary = cv2.threshold(gray, 230, 255, cv2.THRESH_BINARY)
    # 反転: 黒=コマ内容, 白=枠線
    inverted = cv2.bitwise_not(binary)

    # ノイズ除去
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    cleaned = cv2.morphologyEx(inverted, cv2.MORPH_CLOSE, kernel, iterations=2)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)

    # 輪郭検出
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    panels = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cw * ch
        ratio = area / page_area

        # フィルタリング
        if ratio < min_panel_ratio or ratio > max_panel_ratio:
            continue

        # 端すぎるものはスキップ (ページ枠そのもの)
        if x <= border_margin and y <= border_margin and cw >= w - 2 * border_margin and ch >= h - 2 * border_margin:
            continue

        # アスペクト比チェック (極端に細いものは除外)
        aspect = max(cw, ch) / max(min(cw, ch), 1)
        if aspect > 15:
            continue

        panels.append((x, y, x + cw, y + ch))

    # 読み順ソート: 右→左 (漫画)、上→下
    # y 座標でグループ化してから x で右→左ソート
    if panels:
        panels.sort(key=lambda p: (p[1], -p[0]))

    return panels


# ---------------------------------------------------------------------------
# 解析メイン
# ---------------------------------------------------------------------------


def analyze_manga_page(
    image_path: str | Path,
    *,
    do_ocr: bool = True,
    min_panel_ratio: float = 0.02,
    max_panel_ratio: float = 0.9,
) -> MangaPageResult:
    """漫画ページを解析し、パネル・テキスト情報を返す。

    Parameters:
        image_path: 漫画ページ画像のパス
        do_ocr: NDLOCR-Lite でテキスト認識するか
        min_panel_ratio: 最小パネル面積比率
        max_panel_ratio: 最大パネル面積比率

    Returns:
        MangaPageResult
    """
    image_path = Path(image_path)

    # パネル検出 (OpenCV) - 日本語パス対応のため PIL 経由
    pil_img = Image.open(image_path).convert("RGB")
    bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    panel_bboxes = _detect_panels(
        bgr,
        min_panel_ratio=min_panel_ratio,
        max_panel_ratio=max_panel_ratio,
    )
    panels = [PanelInfo(bbox=bbox) for bbox in panel_bboxes]

    # NDLOCR-Lite でテキスト検出 + 認識
    texts: list[TextInfo] = []
    if do_ocr:
        from tag_palette.manga.ndlocr import recognize_page

        ocr_lines = recognize_page(pil_img)
        for line in ocr_lines:
            texts.append(TextInfo(bbox=line.bbox, text=line.text))

    full_text = "\n".join(t.text for t in texts if t.text)

    return MangaPageResult(
        panels=panels,
        texts=texts,
        ocr_full_text=full_text,
    )


def extract_panel_images(
    image_path: str | Path,
    panels: list[PanelInfo],
    *,
    min_size: int = 64,
) -> list[Image.Image]:
    """パネル領域を切り出して PIL Image のリストで返す。"""
    pil_image = Image.open(image_path).convert("RGB")
    crops = []
    for panel in panels:
        x1, y1, x2, y2 = panel.bbox
        w, h = x2 - x1, y2 - y1
        if w < min_size or h < min_size:
            continue
        crops.append(pil_image.crop((x1, y1, x2, y2)))
    return crops
