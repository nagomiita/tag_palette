import logging
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

import numpy as np
from config import LANGUAGE
from db.engine import engine
from db.models import (
    Category,
    Genre,
    ImageEntry,
    ImageTag,
    Pose,
    Tag,
    TagGenre,
    TagTranslation,
)
from sqlalchemy import false, or_, true
from sqlalchemy.orm import Session, joinedload
from tag_config import SENSITIVE_KEYWORDS
from utils.categorize import get_tag_category
from utils.genre import get_genres
from utils.translations import get_translation_for_tag

# パフォーマンス測定用のロガー設定
perf_logger = logging.getLogger("query_performance")
perf_logger.setLevel(logging.INFO)
if not perf_logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - PERF - %(message)s")
    handler.setFormatter(formatter)
    perf_logger.addHandler(handler)


# パフォーマンス測定デコレータ
def measure_time(func_name: str = None, log_threshold: float = 0.001):
    """
    実行時間を測定するデコレータ

    Args:
        func_name: ログに表示する関数名（Noneの場合は実際の関数名）
        log_threshold: この閾値（秒）を超えた場合のみログ出力
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            name = func_name or func.__name__
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start_time
                if elapsed >= log_threshold:
                    perf_logger.info(f"{name}: {elapsed:.4f}s")
                else:
                    perf_logger.debug(f"{name}: {elapsed:.4f}s")

        return wrapper

    return decorator


@contextmanager
def measure_query_time(query_name: str, log_threshold: float = 0.001):
    """
    クエリ実行時間を測定するコンテキストマネージャ

    Args:
        query_name: クエリの名前
        log_threshold: この閾値（秒）を超えた場合のみログ出力
    """
    start_time = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start_time
        if elapsed >= log_threshold:
            perf_logger.info(f"QUERY [{query_name}]: {elapsed:.4f}s")
        else:
            perf_logger.debug(f"QUERY [{query_name}]: {elapsed:.4f}s")


# ---------------------------- Session Management ----------------------------


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


# ---------------------------- Seed: Add Entries ----------------------------


@measure_time("seed_categories_and_tags")
def seed_categories_and_tags():
    category_definitions = [
        "general",
        "artist",
        "copyright",
        "character",
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
            with measure_query_time(f"check_category_{cat_name}"):
                category = session.query(Category).filter_by(name=cat_name).first()
            if not category:
                category = Category(name=cat_name)
                session.add(category)
        with measure_query_time("commit_categories"):
            session.commit()


# ---------------------------- Query: Fetch Entries ----------------------------


@measure_time("get_filtered_image_entries")
def get_filtered_image_entries(
    favorites_only: bool = False, include_sensitive: bool = True
) -> list[ImageEntry]:
    with get_session() as session:
        with measure_query_time("build_filtered_query"):
            query = session.query(ImageEntry)
            if favorites_only:
                query = query.filter(ImageEntry.is_favorite.is_(True))
            if not include_sensitive:
                query = query.filter(ImageEntry.is_sensitive.is_(False))
            query = query.order_by(ImageEntry.id.desc())

        with measure_query_time("execute_filtered_query"):
            return query.all()


@measure_time("get_image_entry_by_id")
def get_image_entry_by_id(image_id: int) -> ImageEntry | None:
    with get_session() as session:
        with measure_query_time(f"get_image_by_id_{image_id}"):
            return session.query(ImageEntry).filter_by(id=image_id).first()


@measure_time("increment_view_count")
def increment_view_count(image_id: int):
    with get_session() as session:
        with measure_query_time(f"get_image_for_view_count_{image_id}"):
            entry = session.get(ImageEntry, image_id)
        if entry:
            entry.view_count += 1
            with measure_query_time(f"commit_view_count_{image_id}"):
                session.commit()


# ---------------------------- Query: Favorite Flags ----------------------------


@measure_time("get_favorite_flag")
def get_favorite_flag(image_id: int) -> bool:
    with get_session() as session:
        with measure_query_time(f"get_favorite_flag_{image_id}"):
            entry = session.query(ImageEntry).filter_by(id=image_id).first()
        return entry.is_favorite if entry else False


@measure_time("toggle_favorite_flag")
def toggle_favorite_flag(image_id: int) -> bool | None:
    with get_session() as session:
        with measure_query_time(f"get_image_for_favorite_{image_id}"):
            entry = session.query(ImageEntry).filter_by(id=image_id).first()
        if entry:
            entry.is_favorite = not entry.is_favorite
            try:
                with measure_query_time(f"commit_favorite_{image_id}"):
                    session.commit()
                return entry.is_favorite
            except Exception:
                session.rollback()
    return None


# ---------------------------- Query: Image Registration ----------------------------


@measure_time("get_registered_image_paths")
def get_registered_image_paths() -> set[str]:
    with get_session() as session:
        with measure_query_time("get_all_image_paths"):
            return {r.image_path for r in session.query(ImageEntry.image_path).all()}


@measure_time("add_image_entry")
def add_image_entry(image_path: Path, thumbnail_path: Path) -> None:
    with get_session() as session:
        session.add(
            ImageEntry(image_path=str(image_path), thumbnail_path=str(thumbnail_path))
        )
        with measure_query_time("commit_single_image"):
            session.commit()


@measure_time("add_image_entries")
def add_image_entries(
    entries: list[tuple[Path, Path, datetime]],
) -> list[tuple[int, str]]:
    """画像エントリをDBに追加し、(id, image_path) のリストを返す"""
    with get_session() as session:
        with measure_query_time(f"create_image_objects_{len(entries)}"):
            image_objects = [
                ImageEntry(
                    image_path=str(orig),
                    thumbnail_path=str(thumb),
                    created_at=created_at,
                )
                for orig, thumb, created_at in entries
            ]

        with measure_query_time(f"add_and_flush_{len(entries)}"):
            session.add_all(image_objects)
            session.flush()  # ✅ IDを確定させる

        results = [(obj.id, obj.image_path) for obj in image_objects]

        with measure_query_time(f"commit_bulk_images_{len(entries)}"):
            session.commit()
        return results


@measure_time("delete_image_entry")
def delete_image_entry(image_id: int) -> bool:
    with get_session() as session:
        with measure_query_time(f"get_image_for_delete_{image_id}"):
            entry = session.query(ImageEntry).filter_by(id=image_id).first()
        if entry:
            session.delete(entry)
            with measure_query_time(f"commit_delete_{image_id}"):
                session.commit()
            return True
    return False


@measure_time("update_image_embedding")
def update_image_embedding(image_id: int, embedding_blob: bytes):
    if not isinstance(embedding_blob, bytes):
        return

    with get_session() as session:
        with measure_query_time(f"get_image_for_embedding_{image_id}"):
            image = session.query(ImageEntry).get(image_id)
        if image:
            image.tag_embedding_blob = embedding_blob  # ✅ バイナリとして保存
            with measure_query_time(f"commit_embedding_{image_id}"):
                session.commit()


# ---------------------------- Query: Pose ----------------------------


@measure_time("add_pose_entry")
def add_pose_entry(image_id: int, vec: np.ndarray, is_flipped: bool):
    with get_session() as session:
        pose = Pose(
            image_id=image_id,
            embedding=vec.tobytes(),
            is_flipped=is_flipped,
        )
        session.add(pose)
        with measure_query_time(f"commit_pose_{image_id}"):
            session.commit()


@measure_time("get_pose_vector_by_image_id")
def get_pose_vector_by_image_id(image_id: int) -> np.ndarray | None:
    """指定した image_id と flip 状態に一致するポーズベクトルを取得"""
    with get_session() as session:
        with measure_query_time(f"get_pose_{image_id}"):
            pose = session.query(Pose).filter(Pose.image_id == image_id).first()
        if pose and pose.embedding:
            return np.frombuffer(pose.embedding, dtype=np.float32)
        return None


@measure_time("load_all_pose_vectors")
def load_all_pose_vectors() -> list[tuple[int, np.ndarray]]:
    """poses テーブルからすべての (image_id, pose_vector) を取得"""
    vectors = []
    with get_session() as session:
        with measure_query_time("get_all_poses"):
            poses = session.query(Pose).all()

        with measure_query_time(f"process_pose_vectors_{len(poses)}"):
            for pose in poses:
                if pose.embedding:
                    vec = np.frombuffer(pose.embedding, dtype=np.float32)
                    vectors.append((pose.image_id, vec))
    return vectors


# ---------------------------- Query: Tag ----------------------------


@measure_time("get_all_tags")
def get_all_tags() -> list[Tag]:
    with get_session() as session:
        with measure_query_time("get_all_tags_ordered"):
            return session.query(Tag).order_by(Tag.name).all()


@measure_time("get_tags_for_image")
def get_tags_for_image(image_id: int, language: str = "en") -> list[str]:
    with get_session() as session:
        with measure_query_time(f"get_image_with_tags_{image_id}"):
            image = session.query(ImageEntry).filter_by(id=image_id).first()
        if not image:
            return []

        tags = []
        with measure_query_time(f"process_image_tags_{image_id}"):
            for image_tag in image.image_tags:
                tag = image_tag.tag
                if language != "en":
                    # 該当言語の翻訳があれば優先
                    with measure_query_time(f"get_translation_{tag.id}"):
                        translation = (
                            session.query(TagTranslation)
                            .filter_by(tag_id=tag.id, language=language)
                            .first()
                        )
                    if translation and translation.translated_name:
                        tags.append(translation.translated_name)
                        continue
                # 翻訳がない or 言語が英語の場合は英語名
                tags.append(tag.name)
        return tags


def is_sensitive(tag: str) -> bool:
    return tag.lower() in SENSITIVE_KEYWORDS


@measure_time("add_tag_entry")
def add_tag_entry(image_id: int, model_name: str, tags: dict[str, float]) -> None:
    with get_session() as session:
        any_sensitive = False

        with measure_query_time(f"process_tags_{len(tags)}"):
            for tag_name, score in tags.items():
                with measure_query_time(f"check_existing_tag_{tag_name}"):
                    existing_tag = session.query(Tag).filter_by(name=tag_name).first()
                newly_created = False

                if not existing_tag:
                    sensitive = is_sensitive(tag_name)
                    existing_tag = Tag(name=tag_name, is_sensitive=sensitive)
                    session.add(existing_tag)
                    session.flush()
                    newly_created = True
                else:
                    sensitive = existing_tag.is_sensitive

                if sensitive:
                    any_sensitive = True

                # ジャンルを追加
                genre_infos = get_genres(existing_tag)
                if genre_infos:
                    for genre_id, genre_name, note in genre_infos:
                        add_genre_to_tag(
                            session, existing_tag.id, genre_id, genre_name, note=note
                        )

                # 翻訳を追加（新規タグの場合のみ）
                if newly_created:
                    tag_translation = get_translation_for_tag(
                        existing_tag.name, language=LANGUAGE
                    )
                    if tag_translation:
                        translation = TagTranslation(
                            tag_id=existing_tag.id,
                            language="ja",
                            translated_name=tag_translation[0]
                            if tag_translation
                            else None,
                            note=tag_translation[1] if tag_translation else None,
                        )
                        session.add(translation)

                    category_name = get_tag_category(existing_tag)
                    if category_name:
                        with measure_query_time(f"get_category_{category_name}"):
                            category = (
                                session.query(Category)
                                .filter_by(name=category_name)
                                .first()
                            )
                        if not category:
                            category = Category(name=category_name)
                            session.add(category)
                            session.flush()
                        if existing_tag.category_id is None:
                            existing_tag.category_id = category.id

                # ImageTag を登録
                image_tag = ImageTag(
                    image_id=image_id,
                    tag_id=existing_tag.id,
                    confidence=score,
                    model_name=model_name,
                )
                session.add(image_tag)

        # 画像にセンシティブ情報を反映
        if any_sensitive:
            with measure_query_time(f"update_sensitive_flag_{image_id}"):
                image_entry = session.query(ImageEntry).get(image_id)
                if image_entry:
                    image_entry.is_sensitive = True

        with measure_query_time(f"commit_tag_entry_{image_id}"):
            session.commit()


def _load_vector_from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


# def _parse_embedding(vec_str: str) -> np.ndarray:
#     if not vec_str or "," not in vec_str:
#         return np.array([])
#     try:
#         vec = np.array(list(map(float, vec_str.split(","))))
#         return vec
#     except ValueError:
#         return np.array([])


@measure_time("get_tag_embedding")
def get_tag_embedding(tag_name: str) -> np.ndarray | None:
    with get_session() as session:
        with measure_query_time(f"get_tag_by_name_{tag_name}"):
            entry = session.query(Tag).filter(Tag.name == tag_name).first()
            if entry and entry.embedding_blob:
                return _load_vector_from_blob(entry.embedding_blob)
        return None


@measure_time("add_tag_embedding")
def add_tag_embedding(tag_name: str, tag_embedding_blob: bytes):
    if not isinstance(tag_embedding_blob, bytes):
        return

    with get_session() as session:
        with measure_query_time(f"get_tag_for_embedding_{tag_name}"):
            tag = session.query(Tag).filter_by(name=tag_name).first()

        if tag:
            tag.embedding_blob = tag_embedding_blob
            with measure_query_time(f"commit_tag_embedding_{tag_name}"):
                session.commit()


@measure_time("get_image_tag_embedding")
def get_image_tag_embedding(image_id: int) -> np.ndarray | None:
    with get_session() as session:
        with measure_query_time(f"get_image_embedding_{image_id}"):
            entry = session.get(ImageEntry, image_id)
        if entry and entry.tag_embedding_blob:
            return _load_vector_from_blob(entry.tag_embedding_blob)
        return None


@measure_time("load_all_image_tag_embedding")
def load_all_image_tag_embedding(
    exclude_id: int | None = None, show_sensitive: bool = True
) -> list[tuple[int, np.ndarray]]:
    with get_session() as session:
        with measure_query_time("build_embedding_query"):
            query = session.query(ImageEntry.id, ImageEntry.tag_embedding_blob).filter(
                ImageEntry.tag_embedding_blob.isnot(None)
            )

            if exclude_id is not None:
                query = query.filter(ImageEntry.id != exclude_id)

            if not show_sensitive:
                query = query.filter(ImageEntry.is_sensitive.is_(False))

        with measure_query_time("execute_embedding_query"):
            entries = query.all()

        with measure_query_time(f"parse_embeddings_{len(entries)}"):
            return [
                (image_id, _load_vector_from_blob(vec_bin))
                for image_id, vec_bin in entries
            ]


@measure_time("get_entries_by_tag")
def get_entries_by_tag(
    keyword: str, favorites_only=False, include_sensitive=True
) -> list[ImageEntry]:
    with get_session() as session:
        with measure_query_time(f"build_single_tag_query_{keyword}"):
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

        with measure_query_time(f"execute_single_tag_query_{keyword}"):
            return query.distinct().all()


@measure_time("get_entries_by_tags")
def get_entries_by_tags(
    tags: list[str],
    search_mode: str = "AND",
    favorites_only: bool = False,
    include_sensitive: bool = True,
) -> list[ImageEntry]:
    """最適化された複数タグ検索"""
    perf_logger.info(f"Starting multi-tag search: {len(tags)} tags, mode={search_mode}")

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

    with measure_query_time("get_base_candidate_ids"):
        base_query = session.query(ImageEntry.id)
        if favorites_only:
            base_query = base_query.filter(ImageEntry.is_favorite == True)
        if not include_sensitive:
            base_query = base_query.filter(ImageEntry.is_sensitive == False)
        candidate_ids = {row[0] for row in base_query.all()}

    if not candidate_ids:
        return []

    for i, tag in enumerate(tags):
        with measure_query_time(f"find_tag_ids_{tag}"):
            matched_tag_ids = {
                row.id
                for row in session.query(Tag.id)
                .filter(Tag.name.ilike(f"%{tag}%"))
                .all()
            }

        if not matched_tag_ids:
            return []

        with measure_query_time(f"find_image_ids_for_tag_{tag}"):
            image_ids = {
                row.image_id
                for row in session.query(ImageTag.image_id)
                .filter(ImageTag.tag_id.in_(matched_tag_ids))
                .all()
            }

        with measure_query_time(f"intersect_candidates_step_{i + 1}"):
            candidate_ids &= image_ids
            perf_logger.info(
                f"After tag '{tag}': {len(candidate_ids)} candidates remain"
            )

        if not candidate_ids:
            return []

    # 最終結果を取得
    with measure_query_time(f"get_final_results_{len(candidate_ids)}"):
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

    with measure_query_time("build_or_query"):
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

        query = query.filter(tag_exists).options(
            joinedload(ImageEntry.image_tags).joinedload(ImageTag.tag)
        )

    with measure_query_time(f"execute_or_query_{len(tags)}_tags"):
        return query.all()


# ---------------------------- Query: TagTranslations ----------------------------


@measure_time("get_tag_translation")
def get_tag_translation(tag_id: int, language: str = "ja") -> TagTranslation | None:
    """指定したタグの日本語翻訳を取得"""
    with get_session() as session:
        with measure_query_time(f"get_translation_{tag_id}_{language}"):
            return (
                session.query(TagTranslation)
                .filter_by(tag_id=tag_id, language=language)
                .first()
            )


@measure_time("add_tag_translation")
def add_tag_translation(
    tag_id: int, language: str, translated_name: str, note: str | None = None
) -> TagTranslation:
    """タグの翻訳を追加または更新"""
    with get_session() as session:
        with measure_query_time(f"check_existing_translation_{tag_id}_{language}"):
            translation = (
                session.query(TagTranslation)
                .filter_by(tag_id=tag_id, language=language)
                .first()
            )
        if translation:
            translation.translated_name = translated_name
            translation.note = note
        else:
            translation = TagTranslation(
                tag_id=tag_id,
                language=language,
                translated_name=translated_name,
                note=note,
            )
            session.add(translation)

        with measure_query_time(f"commit_translation_{tag_id}_{language}"):
            session.commit()
        return translation


# ---------------------------- Query: Category ----------------------------


@measure_time("add_category_by_tag_id")
def add_category_by_tag_id(
    tag_id: int, category_name: str, overwrite: bool = False
) -> None:
    """タグIDにカテゴリを追加・関連付けする"""
    with get_session() as session:
        with measure_query_time(f"get_tag_{tag_id}"):
            tag = session.query(Tag).get(tag_id)
        if not tag:
            return

        with measure_query_time(f"get_category_{category_name}"):
            category = session.query(Category).filter_by(name=category_name).first()
        if not category:
            category = Category(name=category_name)
            session.add(category)
            session.flush()

        if tag.category_id is None or overwrite:
            tag.category_id = category.id
            with measure_query_time(f"commit_category_assignment_{tag_id}"):
                session.commit()


# ---------------------------- Query: Genre ----------------------------


def add_genre_to_tag(
    session: Session,
    tag_id: int,
    genre_id: str,
    genre_name: str | None,
    note: str | None,
    overwrite: bool = False,
) -> None:
    """タグIDにジャンルを追加・関連付けする"""

    with measure_query_time(f"get_tag_for_genre_{tag_id}"):
        tag = session.query(Tag).get(tag_id)
    if not tag:
        return

    with measure_query_time(f"get_genre_{genre_id}"):
        genre = session.query(Genre).filter_by(id=genre_id).first()
    if not genre:
        genre = Genre(id=genre_id, name=genre_name, note=note)
        session.add(genre)
        session.flush()

    with measure_query_time(f"check_existing_tag_genre_{tag_id}_{genre_id}"):
        existing_relation = (
            session.query(TagGenre).filter_by(tag_id=tag_id, genre_id=genre.id).first()
        )

    if existing_relation and not overwrite:
        return

    if existing_relation and overwrite:
        session.delete(existing_relation)
        session.flush()

    relation = TagGenre(tag_id=tag.id, genre_id=genre.id)
    session.add(relation)
    with measure_query_time(f"commit_genre_relation_{tag_id}_{genre_id}"):
        session.commit()


# ---------------------------- Performance Report Helper ----------------------------


def get_performance_summary():
    """パフォーマンス測定の簡易レポートを取得"""
    handler = perf_logger.handlers[0]
    if hasattr(handler, "stream") and hasattr(handler.stream, "getvalue"):
        return handler.stream.getvalue()
    return "Performance logs are being written to console"


def enable_performance_logging(level=logging.INFO):
    """パフォーマンスロギングを有効化"""
    perf_logger.setLevel(level)


def disable_performance_logging():
    """パフォーマンスロギングを無効化"""
    perf_logger.setLevel(logging.CRITICAL)
