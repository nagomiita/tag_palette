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
    created_at = Column(DateTime)
    registered_at = Column(DateTime, default=datetime.now)
    is_favorite = Column(Boolean, default=False)
    is_r18 = Column(Boolean, default=False)
    image_tags = relationship(
        "ImageTag", back_populates="image", cascade="all, delete-orphan"
    )
    poses = relationship("Pose", back_populates="image", cascade="all, delete-orphan")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    genre = Column(String)
    embedding = Column(Text)
    registered_at = Column(DateTime, default=datetime.now)
    is_r18 = Column(Boolean, default=False)
    disable = Column(Boolean, default=False)

    image_tags = relationship(
        "ImageTag", back_populates="tag", cascade="all, delete-orphan"
    )


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


class Genre(Base):
    __tablename__ = "genres"

    name_en = Column(String, primary_key=True)
    name_ja = Column(String)
    registered_at = Column(DateTime, default=datetime.now)
