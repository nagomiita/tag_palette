"""NDLOCR-Lite を Python API として利用するラッパー。

ndlocr-lite リポジトリの DEIM (レイアウト検出) + PARSeq (文字認識) を
直接呼び出し、テキスト行とバウンディングボックスを返す。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from tag_palette.shared.device import get_onnx_device

logger = logging.getLogger(__name__)

_detector = None
_recognizer30 = None
_recognizer50 = None
_recognizer100 = None


@dataclass
class OcrLine:
    """OCR 認識結果の1行。"""

    text: str
    bbox: tuple[int, int, int, int]  # (x, y, x+w, y+h)
    confidence: float = 0.0
    is_vertical: bool = False


def _get_ndlocr_resource_dir() -> Path:
    """ndlocr-lite パッケージのリソースディレクトリを取得する。"""
    import importlib.util
    spec = importlib.util.find_spec("ocr")
    if spec is None or spec.origin is None:
        raise ImportError("ndlocr-lite がインストールされていません: pip install ndlocr-lite")
    return Path(spec.origin).parent


def _load_models():
    """NDLOCR-Lite のモデルを遅延ロードする。"""
    global _detector, _recognizer30, _recognizer50, _recognizer100

    if _detector is not None:
        return

    from deim import DEIM
    from parseq import PARSEQ
    from yaml import safe_load

    resource_dir = _get_ndlocr_resource_dir()
    model_dir = resource_dir / "model"
    config_dir = resource_dir / "config"
    device = get_onnx_device()

    logger.info("NDLOCR-Lite モデルをロード中...")

    _detector = DEIM(
        model_path=str(model_dir / "deim-s-1024x1024.onnx"),
        class_mapping_path=str(config_dir / "ndl.yaml"),
        score_threshold=0.2,
        conf_threshold=0.25,
        iou_threshold=0.2,
        device=device,
    )

    classes_path = str(config_dir / "NDLmoji.yaml")
    with open(classes_path, encoding="utf-8") as f:
        charobj = safe_load(f)
    charlist = list(charobj["model"]["charset_train"])

    def _make_recognizer(weights_name: str) -> PARSEQ:
        return PARSEQ(
            model_path=str(model_dir / weights_name),
            charlist=charlist,
            device=device,
        )

    _recognizer30 = _make_recognizer("parseq-ndl-16x256-30-tiny-192epoch-tegaki3.onnx")
    _recognizer50 = _make_recognizer("parseq-ndl-16x384-50-tiny-146epoch-tegaki2.onnx")
    _recognizer100 = _make_recognizer("parseq-ndl-16x768-100-tiny-165epoch-tegaki2.onnx")

    logger.info("NDLOCR-Lite ロード完了")


def _cascade_recognize(line_images: list[tuple[np.ndarray, int, float]]) -> list[str]:
    """カスケード認識: 文字数予測に応じて適切なモデルを使う。

    Parameters:
        line_images: [(画像, index, pred_char_cnt), ...]

    Returns:
        認識テキストのリスト (入力順)
    """
    _load_models()

    results = [""] * len(line_images)
    batch30, batch50, batch100 = [], [], []

    for img, idx, pred_cnt in line_images:
        if pred_cnt <= 3:
            batch30.append((img, idx))
        elif pred_cnt <= 5:
            batch50.append((img, idx))
        else:
            batch100.append((img, idx))

    # 30文字モデル → オーバーフローは50文字モデルへ
    overflow50 = []
    for img, idx in batch30:
        text = _recognizer30.read(img)
        if len(text) >= 25:
            overflow50.append((img, idx))
        else:
            results[idx] = text

    batch50.extend(overflow50)

    # 50文字モデル → オーバーフローは100文字モデルへ
    overflow100 = []
    for img, idx in batch50:
        text = _recognizer50.read(img)
        if len(text) >= 45:
            overflow100.append((img, idx))
        else:
            results[idx] = text

    batch100.extend(overflow100)

    # 100文字モデル
    for img, idx in batch100:
        text = _recognizer100.read(img)
        results[idx] = text

    return results


def recognize_page(
    image: str | Path | Image.Image | np.ndarray,
    *,
    min_block_confidence: float = 0.54,
    min_line_confidence: float = 0.5,
) -> list[OcrLine]:
    """漫画ページの全テキストを検出・認識する。

    Parameters:
        image: 画像パス、PIL Image、または numpy 配列 (RGB)
        min_block_confidence: テキストブロックの最低信頼度 (これ未満のブロックは除外)
        min_line_confidence: テキスト行の最低信頼度

    Returns:
        OcrLine のリスト
    """
    _load_models()

    import xml.etree.ElementTree as ET
    from ndl_parser import convert_to_xml_string3
    from reading_order.xy_cut.eval import eval_xml

    # 画像をnumpy配列に変換
    if isinstance(image, (str, Path)):
        pil_img = Image.open(image).convert("RGB")
        img = np.array(pil_img)
    elif isinstance(image, Image.Image):
        img = np.array(image.convert("RGB"))
    else:
        img = image

    img_h, img_w = img.shape[:2]

    # レイアウト検出
    detections = _detector.detect(img)
    classeslist = list(_detector.classes.values())

    resultobj = [dict(), dict()]
    resultobj[0][0] = list()
    for i in range(17):
        resultobj[1][i] = []
    for det in detections:
        xmin, ymin, xmax, ymax = det["box"]
        conf = det["confidence"]
        char_count = det["pred_char_count"]
        if det["class_index"] == 0:
            resultobj[0][0].append([xmin, ymin, xmax, ymax])
        resultobj[1][det["class_index"]].append(
            [xmin, ymin, xmax, ymax, conf, char_count]
        )

    # XML 生成 + 読み順決定
    xmlstr = convert_to_xml_string3(img_w, img_h, "page", classeslist, resultobj)
    xmlstr = "<OCRDATASET>" + xmlstr + "</OCRDATASET>"
    root = ET.fromstring(xmlstr)
    eval_xml(root, logger=None)

    # TEXTBLOCK 単位でフィルタリング + テキスト行を切り出し
    import re
    _noise_pattern = re.compile(r'^[\d\s\.\,\;\:\!\?\(\)\)\[\]\/\\\-\+\=\*\&\#\@\%]+$')

    line_images = []
    line_meta = []  # (x, y, w, h, conf, is_vertical, block_conf)
    idx = 0

    for textblock in root.findall(".//TEXTBLOCK"):
        try:
            block_conf = float(textblock.get("CONF", "0"))
        except (TypeError, ValueError):
            block_conf = 0.0

        # ブロック信頼度でフィルタ
        if block_conf < min_block_confidence:
            continue

        for lineobj in textblock.findall("LINE"):
            xmin = int(lineobj.get("X"))
            ymin = int(lineobj.get("Y"))
            line_w = int(lineobj.get("WIDTH"))
            line_h = int(lineobj.get("HEIGHT"))
            try:
                pred_cnt = float(lineobj.get("PRED_CHAR_CNT"))
            except (TypeError, ValueError):
                pred_cnt = 100.0
            try:
                conf = float(lineobj.get("CONF"))
            except (TypeError, ValueError):
                conf = 0.0

            # 行信頼度でフィルタ
            if conf < min_line_confidence:
                continue

            is_vertical = line_h > line_w
            lineimg = img[ymin : ymin + line_h, xmin : xmin + line_w, :]
            line_images.append((lineimg, idx, pred_cnt))
            line_meta.append((xmin, ymin, line_w, line_h, conf, is_vertical, block_conf))
            idx += 1

    if not line_images:
        return []

    # カスケード認識
    texts = _cascade_recognize(line_images)

    # 結果を構築 + ポストフィルタ

    results = []
    for i, text in enumerate(texts):
        if not text or not text.strip():
            continue
        text = text.strip()

        # 数字・記号のみの行を除外
        if _noise_pattern.match(text):
            continue

        # 1文字のみの記号を除外
        if len(text) == 1 and not text.isalpha():
            continue

        x, y, w, h, conf, is_vert, block_conf = line_meta[i]
        results.append(
            OcrLine(
                text=text,
                bbox=(x, y, x + w, y + h),
                confidence=conf,
                is_vertical=is_vert,
            )
        )

    return results
