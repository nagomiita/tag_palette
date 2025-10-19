from typing import List, Optional, Tuple

import numpy as np
from db.models import Pose

from repositories.base import BaseRepository


class PoseRepository(BaseRepository):
    """ポーズに関するデータベース操作"""

    def add_pose(self, image_id: int, vec: np.ndarray, is_flipped: bool) -> None:
        with self.get_session() as session:
            pose = Pose(
                image_id=image_id,
                embedding=vec.tobytes(),
                is_flipped=is_flipped,
            )
            session.add(pose)
            session.commit()

    def get_by_image_id(self, image_id: int) -> Optional[np.ndarray]:
        with self.get_session() as session:
            pose = session.query(Pose).filter(Pose.image_id == image_id).first()
            if pose and pose.embedding:
                return np.frombuffer(pose.embedding, dtype=np.float32)
            return None

    def load_all_vectors(self) -> List[Tuple[int, np.ndarray]]:
        vectors = []
        with self.get_session() as session:
            poses = session.query(Pose).all()
            for pose in poses:
                if pose.embedding:
                    vec = np.frombuffer(pose.embedding, dtype=np.float32)
                    vectors.append((pose.image_id, vec))
        return vectors
