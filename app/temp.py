# dbと接続して、image_pathを全て取得する

from pathlib import Path

from db.query import get_registered_image_paths


def fetch_all_image_paths():
    """
    データベースから全ての画像パスを取得し、image_managerに登録する。
    """
    print("📦 データベースから全ての画像パスを取得中...")
    image_paths = get_registered_image_paths()

    if not image_paths:
        print("ℹ️ 画像パスが見つかりませんでした。")
        return

    print(f"✅ {len(image_paths)} 個の画像パスを取得しました。")
    return [Path(path) for path in image_paths]


# image_pathをもとに、パス先に画像が存在するか確認し、存在しない画像リストを作成する関数。
# tqdmを使う
def check_image_paths_exist(image_paths: list[Path]):
    """
    画像パスのリストを受け取り、存在しない画像のパスをリストアップする。image_managerは使わない
    """
    print("🔍 画像の存在確認を開始します...")

    non_existent_images = []
    for path in image_paths:
        path = path
        if not path.exists():
            non_existent_images.append(str(path))

    if non_existent_images:
        print(f"⚠️ 存在しない画像が {len(non_existent_images)} 個見つかりました。")
        for img in non_existent_images:
            print(f"  - {img}")
    else:
        print("✅ 全ての画像が存在します。")


image_paths = fetch_all_image_paths()
if image_paths:
    check_image_paths_exist(image_paths)
