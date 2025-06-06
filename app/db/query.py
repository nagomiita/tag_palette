from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

import numpy as np
from db.engine import engine
from db.models import ImageEntry, Pose
from sqlalchemy.orm import Session

# ---------------------------- Session Management ----------------------------


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


# ---------------------------- Query: Fetch Entries ----------------------------


def get_all_image_entries() -> list[ImageEntry]:
    with get_session() as session:
        return session.query(ImageEntry).order_by(ImageEntry.id.desc()).all()


def get_favorite_image_entries() -> list[ImageEntry]:
    with get_session() as session:
        return (
            session.query(ImageEntry)
            .filter_by(is_favorite=True)
            .order_by(ImageEntry.id)
            .all()
        )


def get_image_entry_by_id(image_id: int) -> ImageEntry | None:
    with get_session() as session:
        return session.query(ImageEntry).filter_by(id=image_id).first()


# ---------------------------- Query: Favorite Flags ----------------------------


def get_favorite_flag(image_id: int) -> bool:
    with get_session() as session:
        entry = session.query(ImageEntry).filter_by(id=image_id).first()
        return entry.is_favorite if entry else False


def toggle_favorite_flag(image_id: int) -> bool | None:
    with get_session() as session:
        entry = session.query(ImageEntry).filter_by(id=image_id).first()
        if entry:
            entry.is_favorite = not entry.is_favorite
            try:
                session.commit()
                return entry.is_favorite
            except Exception:
                session.rollback()
    return None


# ---------------------------- Query: Image Registration ----------------------------


def get_registered_image_paths() -> set[str]:
    with get_session() as session:
        return {r.image_path for r in session.query(ImageEntry.image_path).all()}


def add_image_entry(image_path: Path, thumbnail_path: Path) -> None:
    with get_session() as session:
        session.add(
            ImageEntry(image_path=str(image_path), thumbnail_path=str(thumbnail_path))
        )
        session.commit()


def add_image_entries(
    entries: list[tuple[Path, Path, datetime]],
) -> list[tuple[int, str]]:
    """
    画像エントリをDBに追加し、(id, image_path) のリストを返す

    Returns:
        List of (id, image_path) tuples
    """
    with get_session() as session:
        image_objects = [
            ImageEntry(
                image_path=str(orig),
                thumbnail_path=str(thumb),
                created_at=created_at,
            )
            for orig, thumb, created_at in entries
        ]
        session.add_all(image_objects)
        session.flush()  # ✅ IDを確定させる

        results = [(obj.id, obj.image_path) for obj in image_objects]

        session.commit()
        return results


def delete_image_entry(image_id: int) -> bool:
    with get_session() as session:
        entry = session.query(ImageEntry).filter_by(id=image_id).first()
        if entry:
            session.delete(entry)
            session.commit()
            return True
    return False


# ---------------------------- Query: Tag ----------------------------
def get_tags_for_image(image_id: int) -> list[str]:
    with get_session() as session:
        image = session.query(ImageEntry).filter_by(id=image_id).first()
        if not image:
            return []
        return ["test"]  # [t.tag.tag for t in image.image_tags]


# ---------------------------- Query: Pose ----------------------------
def add_pose_entry(image_id: int, vec: np.ndarray, is_flipped: bool):
    with get_session() as session:
        pose = Pose(
            image_id=image_id,
            pose_embedding=vec.tobytes(),
            is_flipped=is_flipped,
        )
        session.add(pose)
        session.commit()


def get_pose_vector_by_image_id(image_id: int) -> np.ndarray | None:
    """指定した image_id と flip 状態に一致するポーズベクトルを取得"""
    with get_session() as session:
        pose = session.query(Pose).filter(Pose.image_id == image_id).first()
        if pose and pose.pose_embedding:
            return np.frombuffer(pose.pose_embedding, dtype=np.float32)
        return None


def load_all_pose_vectors() -> list[tuple[int, np.ndarray]]:
    """
    poses テーブルからすべての (image_id, pose_vector) を取得。
    :param is_flipped: 左右反転バージョンを取得するかどうか
    :return: List of (image_id, vector)
    """
    vectors = []
    with get_session() as session:
        poses = session.query(Pose).all()
        for pose in poses:
            if pose.pose_embedding:
                vec = np.frombuffer(pose.pose_embedding, dtype=np.float32)
                vectors.append((pose.image_id, vec))
    return vectors
