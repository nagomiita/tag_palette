import hashlib
from pathlib import Path

from config import DB_PATH, IMAGE_DIR, SUPPORTED_FORMATS, THUMB_DIR, THUMBNAIL_SIZE
from db.models import Base, ImageEntry
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
THUMB_DIR.mkdir(exist_ok=True)


def hash_path(path: Path) -> str:
    return hashlib.md5(str(path).encode("utf-8")).hexdigest()


def initialize_database():
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        registered = {r.image_path for r in session.query(ImageEntry.image_path).all()}
        for img_path in IMAGE_DIR.rglob("*"):
            if (
                img_path.suffix.lower() not in SUPPORTED_FORMATS
                or str(img_path) in registered
            ):
                continue
            thumb_hash = hash_path(img_path)
            thumb_path = THUMB_DIR / f"{thumb_hash}_thumb.png"

            img = Image.open(img_path)
            img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            img.save(thumb_path)

            session.add(
                ImageEntry(image_path=str(img_path), thumbnail_path=str(thumb_path))
            )
        session.commit()


def dispose_engine():
    print("🧹 Disposing SQLAlchemy engine...")
    engine.dispose()
