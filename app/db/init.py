from db.engine import engine
from db.models import Base
from db.query import seed_categories_and_tags
from utils.image import image_manager


def initialize_database():
    print("📦 初期化処理開始: データベース作成")
    Base.metadata.create_all(engine)
    seed_categories_and_tags()
    print("イラストのセットアップ")
    image_manager.register_new_images()


def dispose_engine():
    print("🧹 Disposing SQLAlchemy engine...")
    engine.dispose()
