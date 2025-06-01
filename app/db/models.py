from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ImageEntry(Base):
    __tablename__ = "images"
    id = Column(Integer, primary_key=True)
    image_path = Column(String, nullable=False)
    thumbnail_path = Column(String, nullable=False)
    is_favorite = Column(Boolean, default=False)
