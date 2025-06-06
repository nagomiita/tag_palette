import os

import cv2
import mediapipe as mp
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from utils.logger import setup_logging

logger = setup_logging()

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"
mp_pose = mp.solutions.pose


def __extract_pose_vector(image_path: str, is_flip: bool = False) -> np.ndarray | None:
    img = cv2.imread(image_path)
    if img is None:
        return None
    if is_flip:
        img = cv2.flip(img, 1)

    with mp_pose.Pose(
        static_image_mode=True,
        model_complexity=2,
        enable_segmentation=False,
        min_detection_confidence=0.5,
    ) as pose:
        results = pose.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        if not results.pose_landmarks:
            return None

        landmarks = results.pose_landmarks.landmark
        vector = np.array(
            [[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float32
        ).flatten()
        vector = np.nan_to_num(vector)
        vector /= np.linalg.norm(vector) + 1e-8
        return vector


def process_pose(args: tuple[int, str]) -> list[tuple[int, np.ndarray, bool]]:
    """1画像に対して通常・反転のposeベクトルを抽出する処理"""
    image_id, image_path = args
    results = []
    for is_flipped in [False, True]:
        vec = __extract_pose_vector(image_path, is_flip=is_flipped)
        if vec is not None:
            results.append((image_id, vec, is_flipped))
        else:
            logger.warning(
                f"❌ Pose抽出失敗: image_id={image_id}, flipped={is_flipped}, path={image_path}"
            )
    return results


def search_top_similar_pose_ids(
    query_vec: np.ndarray, db_vectors: list[tuple[int, np.ndarray]], top_k: int = 30
) -> list[int]:
    if query_vec is None or not db_vectors:
        return []

    ids, vecs = zip(*db_vectors)
    sims = cosine_similarity([query_vec], vecs)[0]
    sorted_indices = np.argsort(sims)[::-1]
    return [ids[i] for i in sorted_indices[:top_k]]
