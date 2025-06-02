from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class ImageEntry(Base):
    __tablename__ = "images"
    id = Column(Integer, primary_key=True, autoincrement=True)
    image_path = Column(String, unique=True, nullable=False)
    thumbnail_path = Column(String, unique=True, nullable=False)
    is_favorite = Column(Boolean, default=False)
    tag_embedding = Column(Text)
    pose_embedding = Column(Text)
    image_tags = relationship(
        "ImageTag", back_populates="image", cascade="all, delete-orphan"
    )


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag = Column(String, unique=True, nullable=False)
    translated_tag = Column(String)
    genre = Column(String)
    embedding = Column(Text)
    is_r18 = Column(Boolean, default=False)
    disable = Column(Boolean, default=False)

    image_tags = relationship(
        "ImageTag", back_populates="tag", cascade="all, delete-orphan"
    )


class ImageTag(Base):
    __tablename__ = "image_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_id = Column(
        Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)

    image = relationship("ImageEntry", back_populates="image_tags")
    tag = relationship("Tag", back_populates="image_tags")


class Genre(Base):
    __tablename__ = "genres"

    name_en = Column(String, primary_key=True)
    name_ja = Column(String)
