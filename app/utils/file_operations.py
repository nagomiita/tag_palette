"""
ファイル操作のユーティリティモジュール
より広範囲のファイル操作を含む場合
"""

from pathlib import Path

from utils.clipboard import ClipboardManager


class FileOperationManager:
    """ファイル操作を管理するクラス"""

    def __init__(self, parent_window=None):
        self.parent_window = parent_window

    def copy_image(self, image_path: Path):
        """画像をコピー"""
        return ClipboardManager.copy_image_to_clipboard(image_path, self.parent_window)

    def copy_file_path(self, file_path: Path):
        """ファイルパスをコピー"""
        return ClipboardManager.copy_text_to_clipboard(
            str(file_path),
            self.parent_window,
            "ファイルパスをクリップボードにコピーしました",
        )

    def open_file(self, file_path: Path):
        """ファイルを開く"""
        return ClipboardManager.open_file_with_default_app(
            file_path, self.parent_window
        )
