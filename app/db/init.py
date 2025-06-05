from db.engine import engine
from db.models import Base
from utils.image import image_manager


def initialize_database():
    print("📦 初期化処理開始: データベース作成")
    Base.metadata.create_all(engine)
    image_manager.register_new_images()


def dispose_engine():
    print("🧹 Disposing SQLAlchemy engine...")
    engine.dispose()
