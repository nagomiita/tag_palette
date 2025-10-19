from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BLOB,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ImageEntry(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    image_path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    image_name: Mapped[str | None] = mapped_column(String)
    thumbnail_path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    tag_embedding: Mapped[Optional[str]] = mapped_column(Text)
    tag_embedding_blob: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    created_at: Mapped[Optional[datetime]] = mapped_column()  # ファイル作成日時
    registered_at: Mapped[datetime] = mapped_column(default=func.now())  # 登録日時
    is_favorite: Mapped[bool] = mapped_column(default=False, index=True)
    is_sensitive: Mapped[bool] = mapped_column(default=False, index=True)
    view_count: Mapped[int] = mapped_column(default=0, nullable=False)

    # リレーションシップ
    image_tags: Mapped[List["ImageTag"]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )
    poses: Mapped[List["Pose"]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )
    folder_associations: Mapped[List["ImageFolderAssociation"]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # 基本フィルタリング用インデックス
        Index("idx_images_is_favorite", "is_favorite"),
        Index("idx_images_is_sensitive", "is_sensitive"),
        # 複合検索用インデックス（最重要）
        Index("idx_images_favorite_sensitive", "is_favorite", "is_sensitive"),
        # ソート最適化用インデックス
        Index("idx_images_id_desc", "id"),
    )


class ImageFolderAssociation(Base):
    __tablename__ = "image_folder_associations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    folder_id: Mapped[int] = mapped_column(
        ForeignKey("image_folders.id", ondelete="CASCADE"), nullable=False
    )
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(nullable=False, default=0)  # 順番用

    # リレーションシップ
    folder: Mapped["ImageFolder"] = relationship(back_populates="images")
    image: Mapped["ImageEntry"] = relationship(back_populates="folder_associations")

    __table_args__ = (
        UniqueConstraint("folder_id", "image_id", name="uix_folder_image"),
        Index("idx_folder_image_order", "folder_id", "position"),
    )


class ImageFolder(Base):
    __tablename__ = "image_folders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(default=func.now())

    # リレーションシップ
    images: Mapped[List["ImageFolderAssociation"]] = relationship(
        back_populates="folder", cascade="all, delete-orphan"
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    embedding: Mapped[Optional[str]] = mapped_column(Text)
    embedding_blob: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    registered_at: Mapped[datetime] = mapped_column(default=func.now())
    is_favorite: Mapped[bool] = mapped_column(default=False)
    is_sensitive: Mapped[bool] = mapped_column(default=False, index=True)
    disable: Mapped[bool] = mapped_column(default=False, index=True)

    # リレーションシップ
    category: Mapped[Optional["Category"]] = relationship(back_populates="tags")
    image_tags: Mapped[List["ImageTag"]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )
    translations: Mapped[List["TagTranslation"]] = relationship(
        back_populates="tag", passive_deletes=True
    )
    genre_relations: Mapped[List["TagGenre"]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )

    # 必要最小限のインデックス
    __table_args__ = (
        Index("idx_tags_category_id", "category_id"),
        Index("idx_tags_is_sensitive", "is_sensitive"),
        # センシティブ・無効化の複合検索（よく使用される）
        Index("idx_tags_sensitive_disable", "is_sensitive", "disable"),
    )


class TagTranslation(Base):
    __tablename__ = "tag_translations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), nullable=False
    )
    language: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 例: 'en', 'ja', 'zh'
    translated_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text)  # 補足説明など

    # リレーションシップ
    tag: Mapped["Tag"] = relationship(back_populates="translations")

    __table_args__ = (
        UniqueConstraint("tag_id", "language", name="uix_tag_language"),
        # 言語・タグ複合検索用（重要）
        Index("idx_tag_translations_tag_id", "tag_id"),
        Index("idx_tag_translations_language", "language"),
        Index("idx_tag_translations_tag_language", "tag_id", "language"),
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)

    # リレーションシップ
    tags: Mapped[List["Tag"]] = relationship(
        back_populates="category", passive_deletes=True
    )


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text)  # 補足説明など

    # リレーションシップ
    tag_relations: Mapped[List["TagGenre"]] = relationship(
        back_populates="genre", cascade="all, delete-orphan", passive_deletes=True
    )


class TagGenre(Base):
    __tablename__ = "tag_genres"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), nullable=False
    )
    genre_id: Mapped[str] = mapped_column(
        ForeignKey("genres.id", ondelete="CASCADE"), nullable=False
    )

    # リレーションシップ
    tag: Mapped["Tag"] = relationship(back_populates="genre_relations")
    genre: Mapped["Genre"] = relationship(back_populates="tag_relations")

    # 複合検索用インデックス（重要）
    __table_args__ = (
        Index("idx_tag_genres_tag_id", "tag_id"),
        Index("idx_tag_genres_genre_id", "genre_id"),
        Index("idx_tag_genres_tag_genre", "tag_id", "genre_id"),
    )


class Pose(Base):
    __tablename__ = "poses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    embedding: Mapped[bytes] = mapped_column(BLOB, nullable=False)
    is_flipped: Mapped[bool] = mapped_column(default=False)

    # リレーションシップ
    image: Mapped["ImageEntry"] = relationship(back_populates="poses")

    __table_args__ = (
        UniqueConstraint("image_id", "is_flipped"),
        # 画像・フリップ状態の複合検索用（重要）
        Index("idx_poses_image_id", "image_id"),
        Index("idx_poses_image_flipped", "image_id", "is_flipped"),
    )


class ImageTag(Base):
    __tablename__ = "image_tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), nullable=False
    )
    confidence: Mapped[Optional[float]] = mapped_column()  # タグの信頼度スコア
    model_name: Mapped[Optional[str]] = mapped_column(String)  # 使ったモデル名

    # リレーションシップ
    image: Mapped["ImageEntry"] = relationship(back_populates="image_tags")
    tag: Mapped["Tag"] = relationship(back_populates="image_tags")

    # 最重要なインデックスのみ
    __table_args__ = (
        Index("idx_image_tags_image_id", "image_id"),
        Index("idx_image_tags_tag_id", "tag_id"),
        # 複合検索用インデックス（最重要 - タグから画像を検索）
        Index("idx_image_tags_tag_image", "tag_id", "image_id"),
        # 画像から関連タグを検索
        Index("idx_image_tags_image_tag", "image_id", "tag_id"),
        # 信頼度フィルタリング用（高信頼度タグ検索で使用）
        Index("idx_image_tags_tag_confidence", "tag_id", "confidence"),
    )
