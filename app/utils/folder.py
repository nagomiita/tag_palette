import os
from pathlib import Path
from tkinter import Tk, filedialog

from config import IMAGE_DIR


class ImageLinkManager:
    def __init__(self, image_dir: Path = IMAGE_DIR):
        self.image_dir = image_dir
        self.image_dir.mkdir(exist_ok=True)
        self._clean_broken_symlinks()

    def select_image_folder(self) -> Path | None:
        root = Tk()
        root.withdraw()
        folder_path = filedialog.askdirectory(title="画像フォルダを選択してください")
        root.destroy()
        return Path(folder_path) if folder_path else None

    def create_symlink(self, target: Path):
        try:
            base_name = target.stem
            ext = target.suffix
            counter = 1
            link_path = self.image_dir / (base_name + ext)

            # すでに存在していれば名前をインクリメントして探す
            while link_path.exists() or link_path.is_symlink():
                link_path = self.image_dir / f"{base_name}_{counter}{ext}"
                counter += 1

            os.symlink(target, link_path, target_is_directory=True)
            print(f"🔗 シンボリックリンク作成: {link_path} → {target}")

        except OSError as e:
            print(f"❌ シンボリックリンク作成失敗: {e}")
            raise

    def _clean_broken_symlinks(self):
        for path in self.image_dir.iterdir():
            if path.is_symlink() and not path.resolve().exists():
                print(f"🗑️ リンク切れを削除: {path}")
                path.unlink()


image_link_manager = ImageLinkManager()
