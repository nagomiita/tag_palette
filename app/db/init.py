from pathlib import Path

from db.engine import engine
from db.models import Base
from db.query import add_image_entry, get_registered_image_paths
from utils.folder import clean_broken_symlinks, create_symlink, select_image_folder
from utils.image import find_unregistered_images, generate_thumbnails


def initialize_database():
    print("📦 初期化処理開始: データベース作成")
    Base.metadata.create_all(engine)

    print("🔍 未登録画像パスを取得中...")
    registered = get_registered_image_paths()
    if not registered:
        print("⚠️ 画像がまだ登録されていません。画像フォルダを選択してください。")
        selected_folder = select_image_folder()
        if not selected_folder:
            print("⚠ フォルダが選択されませんでした。処理を中止します。")
            return
        images_dir = Path("images")
        images_dir.mkdir(exist_ok=True)
        clean_broken_symlinks(Path("images"))

        symlink_path = images_dir / selected_folder.name
        create_symlink(selected_folder, symlink_path)
    unregistered = find_unregistered_images(registered)
    if not unregistered:
        print("✅ すでに全ての画像が登録されています。")
        return

    print("🖼 サムネイル画像の生成中...")
    image_paths = generate_thumbnails(unregistered)

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
