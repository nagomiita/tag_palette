import os
import sys
from pathlib import Path
from tkinter import Tk, filedialog


def select_image_folder() -> Path | None:
    root = Tk()
    root.withdraw()
    folder_path = filedialog.askdirectory(title="画像フォルダを選択してください")
    root.destroy()
    return Path(folder_path) if folder_path else None


def create_symlink(target: Path, link_path: Path):
    try:
        if link_path.exists() or link_path.is_symlink():
            print(f"⚠ シンボリックリンクが既に存在: {link_path}")
            return
        os.symlink(target, link_path, target_is_directory=True)
        print(f"🔗 シンボリックリンク作成: {link_path} → {target}")
    except OSError as e:
        print(f"❌ シンボリックリンク作成失敗: {e}")
        sys.exit(1)


def clean_broken_symlinks(base_dir: Path):
    if not base_dir.exists():
        return

    for path in base_dir.iterdir():
        if path.is_symlink() and not path.resolve().exists():
            print(f"🗑️ リンク切れを削除: {path}")
            path.unlink()
