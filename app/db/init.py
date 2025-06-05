from db.engine import engine
from db.models import Base
from db.query import add_image_entries, get_registered_image_paths
from tqdm import tqdm
from utils.folder import image_link_manager
from utils.image import image_manager


def initialize_database():
    print("📦 初期化処理開始: データベース作成")
    Base.metadata.create_all(engine)

    print("🔍 未登録画像パスを取得中...")
    registered = get_registered_image_paths()
    if not registered:
        print("⚠️ 画像がまだ登録されていません。画像フォルダを選択してください。")
        selected_folder = image_link_manager.select_image_folder()
        if selected_folder:
            image_link_manager.create_symlink(selected_folder)
    unregistered = image_manager.find_unregistered_images(registered)
    if not unregistered:
        print("✅ すでに全ての画像が登録されています。")
        return

    print("🖼 サムネイル画像の生成中...")
    image_paths = image_manager.generate_thumbnails(tqdm(unregistered))

    print(f"📥 {len(image_paths)} 件の画像をDBに登録中...")
    add_image_entries(tqdm(image_paths))

    print("\n✅ 初期化完了")


def dispose_engine():
    print("🧹 Disposing SQLAlchemy engine...")
    engine.dispose()
