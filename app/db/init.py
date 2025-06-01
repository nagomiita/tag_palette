from db.engine import engine
from db.models import Base
from db.query import add_image_entry, get_registered_image_paths
from utils.image import resize_images


def initialize_database():
    Base.metadata.create_all(engine)
    registered = get_registered_image_paths()
    image_paths = resize_images(registered)
    for img_path in image_paths:
        add_image_entry(str(img_path[0]), str(img_path[1]))


def dispose_engine():
    print("🧹 Disposing SQLAlchemy engine...")
    engine.dispose()
