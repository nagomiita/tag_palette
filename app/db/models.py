from datetime import datetime

from sqlalchemy import (
    BLOB,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class ImageEntry(Base):
    __tablename__ = "images"
    id = Column(Integer, primary_key=True, autoincrement=True)
    image_path = Column(String, unique=True, nullable=False)
    thumbnail_path = Column(String, unique=True, nullable=False)
    tag_embedding = Column(Text)
    created_at = Column(DateTime)  # ファイル作成日時
    registered_at = Column(DateTime, default=datetime.now)  # 登録日時
    is_favorite = Column(Boolean, default=False)
    is_sensitive = Column(Boolean, default=False)
    view_count = Column(Integer, default=0, nullable=False)
    image_tags = relationship(
        "ImageTag", back_populates="image", cascade="all, delete-orphan"
    )
    poses = relationship("Pose", back_populates="image", cascade="all, delete-orphan")

    # インデックス定義
    __table_args__ = (
        # 基本フィルタリング用インデックス
        Index("idx_images_is_favorite", "is_favorite"),
        Index("idx_images_is_sensitive", "is_sensitive"),
        # 複合検索用インデックス（最重要）
        Index("idx_images_favorite_sensitive", "is_favorite", "is_sensitive"),
        # ソート最適化用インデックス
        Index("idx_images_id_desc", "id"),
        # 埋め込みベクトル検索用（部分インデックス的な効果）
        Index("idx_images_tag_embedding", "tag_embedding"),
        # 日時ソート用
        Index("idx_images_created_at", "created_at"),
        Index("idx_images_registered_at", "registered_at"),
        # ビューカウント用
        Index("idx_images_view_count", "view_count"),
    )


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    category_id = Column(
        Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    embedding = Column(Text)
    registered_at = Column(DateTime, default=datetime.now)
    is_sensitive = Column(Boolean, default=False)
    disable = Column(Boolean, default=False)
    category = relationship("Category", back_populates="tags")
    image_tags = relationship(
        "ImageTag", back_populates="tag", cascade="all, delete-orphan"
    )
    translations = relationship(
        "TagTranslation", back_populates="tag", passive_deletes=True
    )
    genre_relations = relationship(
        "TagGenre", back_populates="tag", cascade="all, delete-orphan"
    )

    # インデックス定義
    __table_args__ = (
        # タグ名検索用（LIKE検索対応）
        Index("idx_tags_name", "name"),
        # カテゴリ検索用
        Index("idx_tags_category_id", "category_id"),
        # 埋め込みベクトル検索用
        Index("idx_tags_embedding", "embedding"),
        # センシティブフィルタ用
        Index("idx_tags_is_sensitive", "is_sensitive"),
        # 無効化フィルタ用
        Index("idx_tags_disable", "disable"),
        # 複合検索用
        Index("idx_tags_sensitive_disable", "is_sensitive", "disable"),
        # 登録日時ソート用
        Index("idx_tags_registered_at", "registered_at"),
    )


class TagTranslation(Base):
    __tablename__ = "tag_translations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    language = Column(String, nullable=False)  # 例: 'en', 'ja', 'zh'
    translated_name = Column(String, nullable=False)
    note = Column(Text, nullable=True)  # 補足説明など（任意）

    tag = relationship("Tag", back_populates="translations")

    __table_args__ = (
        UniqueConstraint("tag_id", "language", name="uix_tag_language"),
        # インデックス定義
        Index("idx_tag_translations_tag_id", "tag_id"),
        Index("idx_tag_translations_language", "language"),
        Index("idx_tag_translations_tag_language", "tag_id", "language"),
        Index("idx_tag_translations_translated_name", "translated_name"),
    )


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)

    tags = relationship("Tag", back_populates="category", passive_deletes=True)

    # インデックス定義
    __table_args__ = (Index("idx_categories_name", "name"),)


class Genre(Base):
    __tablename__ = "genres"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    note = Column(Text, nullable=True)  # 補足説明など（任意）
    tag_relations = relationship(
        "TagGenre",
        back_populates="genre",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # インデックス定義
    __table_args__ = (Index("idx_genres_name", "name"),)


class TagGenre(Base):
    __tablename__ = "tag_genres"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    genre_id = Column(
        String, ForeignKey("genres.id", ondelete="CASCADE"), nullable=False
    )

    tag = relationship("Tag", back_populates="genre_relations")
    genre = relationship("Genre", back_populates="tag_relations")

    # インデックス定義
    __table_args__ = (
        Index("idx_tag_genres_tag_id", "tag_id"),
        Index("idx_tag_genres_genre_id", "genre_id"),
        Index("idx_tag_genres_tag_genre", "tag_id", "genre_id"),
    )


class Pose(Base):
    __tablename__ = "poses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_id = Column(
        Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    embedding = Column(BLOB, nullable=False)
    is_flipped = Column(Boolean, default=False)

    image = relationship("ImageEntry", back_populates="poses")

    __table_args__ = (
        UniqueConstraint("image_id", "is_flipped"),
        # インデックス定義
        Index("idx_poses_image_id", "image_id"),
        Index("idx_poses_is_flipped", "is_flipped"),
        Index("idx_poses_image_flipped", "image_id", "is_flipped"),
    )


class ImageTag(Base):
    __tablename__ = "image_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_id = Column(
        Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    confidence = Column(Float, nullable=True)  # タグの信頼度スコア（例: 0.932）
    model_name = Column(String, nullable=True)  # 使ったモデル名（例: "wd14-vit.v2"）

    image = relationship("ImageEntry", back_populates="image_tags")
    tag = relationship("Tag", back_populates="image_tags")

    # インデックス定義
    __table_args__ = (
        # 基本的な外部キーインデックス
        Index("idx_image_tags_image_id", "image_id"),
        Index("idx_image_tags_tag_id", "tag_id"),
        # 複合検索用インデックス（最重要）
        Index("idx_image_tags_tag_image", "tag_id", "image_id"),
        Index("idx_image_tags_image_tag", "image_id", "tag_id"),
        # 信頼度でのフィルタリング用
        Index("idx_image_tags_confidence", "confidence"),
        # モデル名でのフィルタリング用
        Index("idx_image_tags_model_name", "model_name"),
        # 複合検索用（信頼度込み）
        Index("idx_image_tags_tag_confidence", "tag_id", "confidence"),
        Index("idx_image_tags_image_confidence", "image_id", "confidence"),
    )
