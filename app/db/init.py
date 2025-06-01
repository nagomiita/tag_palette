import hashlib
from pathlib import Path

from config import THUMB_DIR
from db.engine import engine
from db.models import Base
from db.query import add_image_entry, get_registered_image_paths
from utils.image import resize_images

THUMB_DIR.mkdir(exist_ok=True)


def hash_path(path: Path) -> str:
    return hashlib.md5(str(path).encode("utf-8")).hexdigest()


def initialize_database():
    Base.metadata.create_all(engine)
    registered = get_registered_image_paths()
    image_paths = resize_images(registered)
    for img_path in image_paths:
        add_image_entry(str(img_path[0]), str(img_path[1]))


def dispose_engine():
    print("🧹 Disposing SQLAlchemy engine...")
    engine.dispose()
