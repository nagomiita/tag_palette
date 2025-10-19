from typing import Dict, List, Optional

import numpy as np
from db.models import ImageEntry, Tag, TagTranslation

from repositories.base import BaseRepository


class TagRepository(BaseRepository):
    """タグに関するデータベース操作"""

    def get_all(self) -> List[Tag]:
        with self.get_session() as session:
            return session.query(Tag).order_by(Tag.name).all()

    def get_tags_for_image(self, image_id: int, language: str = "en") -> List[str]:
        with self.get_session() as session:
            image = session.query(ImageEntry).filter_by(id=image_id).first()
            if not image:
                return []

            tags = []
            for image_tag in image.image_tags:
                tag = image_tag.tag
                if language != "en":
                    translation = (
                        session.query(TagTranslation)
                        .filter_by(tag_id=tag.id, language=language)
                        .first()
                    )
                    if translation and translation.translated_name:
                        tags.append(translation.translated_name)
                        continue
                tags.append(tag.name)
            return tags

    def add_tags_to_image(
        self,
        image_id: int,
        model_name: str,
        tags: Dict[str, float],
        tag_service=None,  # TagServiceを注入
    ) -> None:
        """タグサービスと連携してタグを追加"""
        # 実装は既存のadd_tag_entryと同様
        pass

    def get_embedding(self, tag_name: str) -> Optional[np.ndarray]:
        with self.get_session() as session:
            entry = session.query(Tag).filter(Tag.name == tag_name).first()
            if entry and entry.embedding:
                return self._parse_embedding(entry.embedding)
            return None

    def update_embedding(self, tag_name: str, tag_embedding: str) -> None:
        if not self._is_valid_embedding(tag_embedding):
            print(f"[SKIP] 無効なベクトル: {tag_name} → {tag_embedding}")
            return

        with self.get_session() as session:
            tag = session.query(Tag).filter_by(name=tag_name).first()
            if tag:
                tag.embedding = tag_embedding
                session.commit()

    def _parse_embedding(self, vec_str: str) -> np.ndarray:
        if not vec_str or "," not in vec_str:
            return np.array([])
        try:
            return np.array(list(map(float, vec_str.split(","))))
        except ValueError:
            return np.array([])

    def _is_valid_embedding(self, embedding: str) -> bool:
        return embedding and isinstance(embedding, str) and "," in embedding
