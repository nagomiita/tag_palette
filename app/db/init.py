from db.engine import engine
from db.models import Base
from db.query import add_image_entry, get_registered_image_paths
from utils.image import resize_images


def initialize_database():
    print("📦 初期化処理開始: データベース作成")
    Base.metadata.create_all(engine)

    print("🔍 既存の登録画像パスを取得中...")
    registered = get_registered_image_paths()

    print("🖼 サムネイル画像の生成中...")
    image_paths = resize_images(registered)

    print(f"📥 {len(image_paths)} 件の画像をDBに登録中...")
    for idx, (original_path, thumb_path) in enumerate(image_paths, start=1):
        print(f"  [{idx}/{len(image_paths)}] 登録中: {original_path}")
        add_image_entry(str(original_path), str(thumb_path))

    print("✅ 初期化完了")


def dispose_engine():
    print("🧹 Disposing SQLAlchemy engine...")
    engine.dispose()
