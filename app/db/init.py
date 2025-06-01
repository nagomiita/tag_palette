import hashlib
from pathlib import Path

from config import IMAGE_DIR, SUPPORTED_FORMATS, THUMB_DIR, THUMBNAIL_SIZE
from db.engine import engine
from db.models import Base
from db.query import add_image_entry, get_registered_image_paths
from PIL import Image

THUMB_DIR.mkdir(exist_ok=True)


def hash_path(path: Path) -> str:
    return hashlib.md5(str(path).encode("utf-8")).hexdigest()


def initialize_database():
    Base.metadata.create_all(engine)
    registered = get_registered_image_paths()
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

        add_image_entry(str(img_path), str(thumb_path))


def dispose_engine():
    print("🧹 Disposing SQLAlchemy engine...")
    engine.dispose()
