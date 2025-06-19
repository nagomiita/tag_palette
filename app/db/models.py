from datetime import datetime

from sqlalchemy import (
    BLOB,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
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


class TagTranslation(Base):
    __tablename__ = "tag_translations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    language = Column(String, nullable=False)  # 例: 'en', 'ja', 'zh'
    translated_name = Column(String, nullable=False)
    note = Column(Text, nullable=True)  # 補足説明など（任意）

    tag = relationship("Tag", back_populates="translations")

    __table_args__ = (UniqueConstraint("tag_id", "language", name="uix_tag_language"),)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)

    tags = relationship("Tag", back_populates="category", passive_deletes=True)


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


class TagGenre(Base):
    __tablename__ = "tag_genres"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    genre_id = Column(
        String, ForeignKey("genres.id", ondelete="CASCADE"), nullable=False
    )

    tag = relationship("Tag", back_populates="genre_relations")
    genre = relationship("Genre", back_populates="tag_relations")


class Pose(Base):
    __tablename__ = "poses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_id = Column(
        Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    embedding = Column(BLOB, nullable=False)
    is_flipped = Column(Boolean, default=False)

    __table_args__ = (UniqueConstraint("image_id", "is_flipped"),)

    image = relationship("ImageEntry", back_populates="poses")


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
