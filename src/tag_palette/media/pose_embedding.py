"""ポーズ推定 → 固定長ベクトル化モジュール。

DWPose (imgutils) でアニメ画像からキーポイントを抽出し、
スケール・位置に依存しない固定長ベクトルに変換する。

ベクトル構成 (body_only=True, デフォルト):
  - 正規化座標: 18点 × 2 (x, y) = 36次元
  - 信頼度:     18点 × 1         = 18次元
  - 関節角度:   10角度            = 10次元
  合計: 64次元

ベクトル構成 (body_only=False):
  - 正規化座標: 136点 × 2 (x, y) = 272次元
  - 信頼度:     136点 × 1         = 136次元
  合計: 408次元
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from imgutils.pose.format import OP18KeyPointSet

logger = logging.getLogger(__name__)

# 関節角度の計算に使う三点組 (parent, joint, child)
# OpenPose18 のインデックス
_ANGLE_TRIPLETS: list[tuple[int, int, int]] = [
    (1, 2, 3),   # 右肩 (首→右肩→右肘)
    (2, 3, 4),   # 右肘 (右肩→右肘→右手首)
    (1, 5, 6),   # 左肩 (首→左肩→左肘)
    (5, 6, 7),   # 左肘 (左肩→左肘→左手首)
    (1, 8, 9),   # 右股関節 (首→右ヒップ→右膝) — 首を上体の代表として使用
    (8, 9, 10),  # 右膝 (右ヒップ→右膝→右足首)
    (1, 11, 12), # 左股関節 (首→左ヒップ→左膝)
    (11, 12, 13),# 左膝 (左ヒップ→左膝→左足首)
    (2, 1, 5),   # 首の傾き (右肩→首→左肩)
    (8, 1, 11),  # 腰の開き (右ヒップ→首→左ヒップ) — 体幹の開き具合
]


def _compute_angle(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray) -> float:
    """三点 p1-p2-p3 のなす角 (ラジアン, 0〜π) を返す。

    いずれかの点の信頼度が低い場合は 0.0 を返す。
    """
    v1 = p1[:2] - p2[:2]
    v2 = p3[:2] - p2[:2]
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 < 1e-6 or norm2 < 1e-6:
        return 0.0
    cos_val = np.dot(v1, v2) / (norm1 * norm2)
    cos_val = np.clip(cos_val, -1.0, 1.0)
    return float(np.arccos(cos_val))


def _normalize_keypoints(body: np.ndarray) -> np.ndarray:
    """体キーポイントをスケール・位置に依存しない座標に正規化する。

    - 首 (index 1) を原点に平行移動
    - 首→鼻の距離で正規化 (検出不能時は首→肩の距離にフォールバック)
    - 信頼度が低い点 (< 0.1) の座標は 0 にする
    """
    coords = body[:, :2].copy()
    confs = body[:, 2].copy()

    # 低信頼度の点をマスク
    low_conf = confs < 0.1
    coords[low_conf] = 0.0

    # 首を原点に
    neck = coords[1].copy()
    if confs[1] < 0.1:
        # 首が検出されない場合は検出された点の重心
        valid = ~low_conf
        if valid.any():
            neck = coords[valid].mean(axis=0)
        else:
            return np.zeros_like(coords)

    coords -= neck

    # スケール正規化: 首→鼻 の距離
    scale = 1.0
    if confs[0] >= 0.1 and confs[1] >= 0.1:
        d = np.linalg.norm(coords[0])
        if d > 1e-6:
            scale = d
    elif confs[2] >= 0.1 and confs[5] >= 0.1:
        # フォールバック: 肩幅
        d = np.linalg.norm(coords[2] - coords[5])
        if d > 1e-6:
            scale = d

    coords /= scale
    coords[low_conf] = 0.0

    return coords


def keypoints_to_vector(
    kp: OP18KeyPointSet,
    body_only: bool = True,
) -> np.ndarray:
    """OP18KeyPointSet を固定長ベクトルに変換する。

    Args:
        kp: DWPose の推定結果 (1人分)
        body_only: True なら体 18 点 + 角度 (64次元)、
                   False なら全 136 点 (408次元)

    Returns:
        float32 の1次元ベクトル
    """
    if body_only:
        body = kp.body  # (18, 3)
        normalized = _normalize_keypoints(body)
        confs = body[:, 2]

        # 関節角度
        angles = np.array([
            _compute_angle(body[a], body[b], body[c])
            for a, b, c in _ANGLE_TRIPLETS
        ], dtype=np.float32)
        # π で正規化 → 0〜1
        angles /= np.pi

        vec = np.concatenate([
            normalized.flatten(),   # 36 次元
            confs,                  # 18 次元
            angles,                 # 10 次元
        ])
    else:
        all_kp = kp.all  # (136, 3)
        vec = all_kp.flatten()  # 408 次元

    return vec.astype(np.float32)


def extract_pose_embedding(
    image_path: str | Path,
    body_only: bool = True,
) -> np.ndarray | None:
    """画像からポーズ推定 → ベクトル化する。

    複数人物が検出された場合、最も検出面積が大きい人物を使用する。

    Args:
        image_path: 画像ファイルパス
        body_only: 体キーポイントのみ使用するか

    Returns:
        固定長 float32 ベクトル。人物が検出されない場合は None。
    """
    from imgutils.pose import dwpose_estimate

    keypoints_list = dwpose_estimate(str(image_path))

    if not keypoints_list:
        return None

    if len(keypoints_list) == 1:
        kp = keypoints_list[0]
    else:
        # 最も大きい人物を選択 (体キーポイントのバウンディングボックス面積)
        def _bbox_area(kp: OP18KeyPointSet) -> float:
            body = kp.body
            valid = body[:, 2] >= 0.1
            if not valid.any():
                return 0.0
            coords = body[valid, :2]
            return float(
                (coords[:, 0].max() - coords[:, 0].min())
                * (coords[:, 1].max() - coords[:, 1].min())
            )

        kp = max(keypoints_list, key=_bbox_area)

    # 体キーポイントの有効点数チェック
    valid_count = (kp.body[:, 2] >= 0.1).sum()
    if valid_count < 4:
        logger.debug("有効キーポイントが少なすぎます (%d/18): %s", valid_count, image_path)
        return None

    return keypoints_to_vector(kp, body_only=body_only)


def pose_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """2つのポーズベクトルのコサイン類似度を返す (0〜1)。"""
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    if norm1 < 1e-8 or norm2 < 1e-8:
        return 0.0
    return float(np.dot(vec1, vec2) / (norm1 * norm2))


def embedding_to_bytes(vec: np.ndarray) -> bytes:
    """ベクトルを float32 バイト列に変換 (DB 保存用)。"""
    return vec.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """バイト列から float32 ベクトルを復元する。"""
    return np.frombuffer(data, dtype=np.float32)
