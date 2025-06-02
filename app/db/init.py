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

    total = len(image_paths)
    for idx, (original_path, thumb_path) in enumerate(image_paths, start=1):
        # シンプルな進捗バー表示
        progress = int(50 * idx / total)  # 50文字の進捗バー
        bar = "█" * progress + "-" * (50 - progress)
        percent = 100 * idx / total

        print(f"\r[{bar}] {percent:.1f}% ({idx}/{total})", end="", flush=True)

        add_image_entry(str(original_path), str(thumb_path))

    print("\n✅ 初期化完了")


def dispose_engine():
    print("🧹 Disposing SQLAlchemy engine...")
    engine.dispose()
