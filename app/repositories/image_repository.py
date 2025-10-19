from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from db.models import ImageEntry

from repositories.base import BaseRepository


class ImageRepository(BaseRepository):
    """画像エントリに関するデータベース操作"""

    def get_filtered_entries(
        self, favorites_only: bool = False, include_sensitive: bool = True
    ) -> List[ImageEntry]:
        with self.get_session() as session:
            query = session.query(ImageEntry)
            if favorites_only:
                query = query.filter(ImageEntry.is_favorite.is_(True))
            if not include_sensitive:
                query = query.filter(ImageEntry.is_sensitive.is_(False))
            return query.order_by(ImageEntry.id.desc()).all()

    def get_by_id(self, image_id: int) -> Optional[ImageEntry]:
        with self.get_session() as session:
            return session.query(ImageEntry).filter_by(id=image_id).first()

    def increment_view_count(self, image_id: int) -> None:
        with self.get_session() as session:
            entry = session.get(ImageEntry, image_id)
            if entry:
                entry.view_count += 1
                session.commit()

    def toggle_favorite(self, image_id: int) -> Optional[bool]:
        with self.get_session() as session:
            entry = session.query(ImageEntry).filter_by(id=image_id).first()
            if entry:
                entry.is_favorite = not entry.is_favorite
                try:
                    session.commit()
                    return entry.is_favorite
                except Exception:
                    session.rollback()
        return None

    def add_entries(
        self, entries: List[Tuple[Path, Path, datetime]]
    ) -> List[Tuple[int, str]]:
        with self.get_session() as session:
            image_objects = [
                ImageEntry(
                    image_path=str(orig),
                    thumbnail_path=str(thumb),
                    created_at=created_at,
                )
                for orig, thumb, created_at in entries
            ]
            session.add_all(image_objects)
            session.flush()
            results = [(obj.id, obj.image_path) for obj in image_objects]
            session.commit()
            return results

    def delete(self, image_id: int) -> bool:
        with self.get_session() as session:
            entry = session.query(ImageEntry).filter_by(id=image_id).first()
            if entry:
                session.delete(entry)
                session.commit()
                return True
        return False

    def update_embedding(self, image_id: int, embedding: np.ndarray) -> None:
        vec_str = ",".join(map(str, embedding.tolist()))
        with self.get_session() as session:
            image = session.query(ImageEntry).get(image_id)
            if image:
                image.tag_embedding = vec_str
