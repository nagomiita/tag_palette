from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

import numpy as np
from db.engine import engine
from db.models import (  # Baseクラスが定義されたモジュール名に応じて修正
    Category,
    ImageEntry,
    ImageTag,
    Pose,
    Tag,
)
from sqlalchemy import false, or_, true
from sqlalchemy.orm import Session, joinedload
from tag_config import SENSITIVE_KEYWORDS

# ---------------------------- Session Management ----------------------------


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


# ---------------------------- Seed: Add Entries ----------------------------


def seed_categories_and_tags():
    category_definitions = [
        "pose",
        "costume",
        "appearance",
        "emotion",
        "composition",
        "background",
        "fantasy",
        "meta",
    ]
    with get_session() as session:
        for cat_name in category_definitions:
            category = session.query(Category).filter_by(name=cat_name).first()
            if not category:
                category = Category(name=cat_name)
                session.add(category)
        session.commit()


# ---------------------------- Query: Fetch Entries ----------------------------


def get_filtered_image_entries(
    favorites_only: bool = False, include_sensitive: bool = True
) -> list[ImageEntry]:
    with get_session() as session:
        query = session.query(ImageEntry)
        if favorites_only:
            query = query.filter(ImageEntry.is_favorite.is_(True))
        if not include_sensitive:
            query = query.filter(ImageEntry.is_sensitive.is_(False))
        return query.order_by(ImageEntry.id.desc()).all()


def get_image_entry_by_id(image_id: int) -> ImageEntry | None:
    with get_session() as session:
        return session.query(ImageEntry).filter_by(id=image_id).first()


def increment_view_count(image_id: int):
    with get_session() as session:
        entry = session.get(ImageEntry, image_id)
        if entry:
            entry.view_count += 1
            session.commit()


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


def update_image_embedding(image_id: int, embedding: np.ndarray):
    vec_str = ",".join(map(str, embedding.tolist()))
    with get_session() as session:
        image = session.query(ImageEntry).get(image_id)
        if image:
            image.tag_embedding = vec_str
            session.commit()


# ---------------------------- Query: Pose ----------------------------
def add_pose_entry(image_id: int, vec: np.ndarray, is_flipped: bool):
    with get_session() as session:
        pose = Pose(
            image_id=image_id,
            embedding=vec.tobytes(),
            is_flipped=is_flipped,
        )
        session.add(pose)
        session.commit()


def get_pose_vector_by_image_id(image_id: int) -> np.ndarray | None:
    """指定した image_id と flip 状態に一致するポーズベクトルを取得"""
    with get_session() as session:
        pose = session.query(Pose).filter(Pose.image_id == image_id).first()
        if pose and pose.embedding:
            return np.frombuffer(pose.embedding, dtype=np.float32)
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
            if pose.embedding:
                vec = np.frombuffer(pose.embedding, dtype=np.float32)
                vectors.append((pose.image_id, vec))
    return vectors


# ---------------------------- Query: Tag ----------------------------
def get_tags_for_image(image_id: int) -> list[str]:
    with get_session() as session:
        image = session.query(ImageEntry).filter_by(id=image_id).first()
        if not image:
            return []
        return [t.tag.name for t in image.image_tags]


def is_sensitive(tag: str) -> bool:
    if tag.lower() in SENSITIVE_KEYWORDS:
        return True
    return False


def add_tag_entry(image_id: int, model_name: str, tags: dict[str, float]):
    with get_session() as session:
        any_sensitive = False

        for tag_name, score in tags.items():
            existing_tag = session.query(Tag).filter_by(name=tag_name).first()
            if not existing_tag:
                sensitive = is_sensitive(tag_name)
                existing_tag = Tag(name=tag_name, is_sensitive=sensitive)
                session.add(existing_tag)
                session.flush()
            else:
                sensitive = existing_tag.is_sensitive

            if sensitive:
                any_sensitive = True

            # ImageTag を登録
            image_tag = ImageTag(
                image_id=image_id,
                tag_id=existing_tag.id,
                confidence=score,
                model_name=model_name,
            )
            session.add(image_tag)

        if any_sensitive:
            image_entry = session.query(ImageEntry).get(image_id)
            if image_entry:
                image_entry.is_sensitive = True
        session.commit()


def _parse_embedding(vec_str: str) -> np.ndarray:
    if not vec_str or "," not in vec_str:
        print("[WARN] 無効な埋め込み文字列です:", vec_str)
        return np.array([])
    try:
        vec = np.array(list(map(float, vec_str.split(","))))
        return vec
    except ValueError as e:
        print(f"[ERROR] ベクトルのパースに失敗: {vec_str} → {e}")
        return np.array([])


def get_tag_embedding(tag_name: str) -> np.ndarray | None:
    with get_session() as session:
        entry = session.query(Tag).filter(Tag.name == tag_name).first()
        if entry and entry.embedding:
            return _parse_embedding(entry.embedding)
        return None


def add_tag_embedding(tag_name: str, tag_embedding: str):
    if (
        not tag_embedding
        or not isinstance(tag_embedding, str)
        or "," not in tag_embedding
    ):
        print(f"[SKIP] 無効なベクトルは保存しません: {tag_name} → {tag_embedding}")
        return

    with get_session() as session:
        tag = session.query(Tag).filter_by(name=tag_name).first()
        if tag:
            tag.embedding = tag_embedding
            session.commit()
        else:
            print(f"Tag '{tag_name}' が見つかりませんでした。")


def get_image_tag_embedding(image_id: int) -> np.ndarray | None:
    with get_session() as session:
        entry = session.get(ImageEntry, image_id)
        if entry and entry.tag_embedding:
            return _parse_embedding(entry.tag_embedding)
        return None


def load_all_image_tag_embedding(
    exclude_id: int | None = None, show_sensitive: bool = True
) -> list[tuple[int, np.ndarray]]:
    with get_session() as session:
        query = session.query(ImageEntry.id, ImageEntry.tag_embedding).filter(
            ImageEntry.tag_embedding.isnot(None)
        )

        if exclude_id is not None:
            query = query.filter(ImageEntry.id != exclude_id)

        if not show_sensitive:
            query = query.filter(ImageEntry.is_sensitive.is_(False))

        entries = query.all()
        return [(image_id, _parse_embedding(vec_str)) for image_id, vec_str in entries]


def get_entries_by_tag(
    keyword: str, favorites_only=False, include_sensitive=True
) -> list[ImageEntry]:
    with get_session() as session:
        query = (
            session.query(ImageEntry)
            .join(ImageEntry.image_tags)
            .join(ImageTag.tag)
            .filter(Tag.name.ilike(f"%{keyword}%"))
        )

        if favorites_only:
            query = query.filter(ImageEntry.is_favorite == true())
        if not include_sensitive:
            query = query.filter(ImageEntry.is_sensitive == false())
        query = query.options(
            joinedload(ImageEntry.image_tags).joinedload(ImageTag.tag)
        )

        return query.distinct().all()


def get_entries_by_tags(
    tags: list[str],
    search_mode: str = "AND",
    favorites_only: bool = False,
    include_sensitive: bool = True,
) -> list[ImageEntry]:
    """最適化された複数タグ検索

    Args:
        tags: 検索タグのリスト
        search_mode: 'AND' または 'OR'
        favorites_only: お気に入りのみ
        include_sensitive: センシティブ画像を含む

    Returns:
        マッチした画像エントリのリスト
    """
    with get_session() as session:
        if search_mode.upper() == "AND":
            return _search_tags_and_optimized(
                session, tags, favorites_only, include_sensitive
            )
        else:
            return _search_tags_or_optimized(
                session, tags, favorites_only, include_sensitive
            )


def _search_tags_and_optimized(
    session: Session, tags: list[str], favorites_only: bool, include_sensitive: bool
) -> list[ImageEntry]:
    """段階的フィルタリングによるAND検索（推奨）"""

    # Step 1: 基本フィルタで画像IDセットを取得
    candidate_ids = set()

    base_query = session.query(ImageEntry.id)
    if favorites_only:
        base_query = base_query.filter(ImageEntry.is_favorite == True)
    if not include_sensitive:
        base_query = base_query.filter(ImageEntry.is_sensitive == False)

    candidate_ids = {row[0] for row in base_query.all()}

    if not candidate_ids:
        return []

    for tag in tags:
        matched_tag_ids = {
            row.id
            for row in session.query(Tag.id).filter(Tag.name.ilike(f"%{tag}%")).all()
        }

        if not matched_tag_ids:
            return []

        image_ids = {
            row.image_id
            for row in session.query(ImageTag.image_id)
            .filter(ImageTag.tag_id.in_(matched_tag_ids))
            .all()
        }

        candidate_ids &= image_ids
        if not candidate_ids:
            return []

    # Step 3: 最終結果を取得
    return (
        session.query(ImageEntry)
        .filter(ImageEntry.id.in_(candidate_ids))
        .options(joinedload(ImageEntry.image_tags).joinedload(ImageTag.tag))
        .order_by(ImageEntry.id.desc())
        .all()
    )


def _search_tags_or_optimized(
    session: Session, tags: list[str], favorites_only: bool, include_sensitive: bool
) -> list[ImageEntry]:
    """最適化されたOR検索：効率的なJOIN"""

    # 基本クエリ
    query = session.query(ImageEntry)

    # 基本フィルタを先に適用
    if favorites_only:
        query = query.filter(ImageEntry.is_favorite == True)
    if not include_sensitive:
        query = query.filter(ImageEntry.is_sensitive == False)

    # EXISTS を使った効率的なタグ検索
    tag_exists = (
        session.query(ImageTag.image_id)
        .join(Tag)
        .filter(
            ImageTag.image_id == ImageEntry.id,
            or_(*[Tag.name.ilike(f"%{tag}%") for tag in tags]),
        )
        .exists()
    )

    return (
        query.filter(tag_exists)
        .options(joinedload(ImageEntry.image_tags).joinedload(ImageTag.tag))
        .all()
    )
