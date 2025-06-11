"""
クリップボード操作のユーティリティモジュール
- 画像コピー
- テキストコピー
- ファイル操作
"""

import io
import os
import platform
from pathlib import Path
from tkinter import messagebox

from PIL import Image


class ClipboardManager:
    """クリップボード操作を管理するクラス"""

    @staticmethod
    def copy_image_to_clipboard(image_path: Path, parent_window=None) -> bool:
        """画像をクリップボードにコピー"""
        try:
            image = Image.open(image_path)

            # Windows の場合
            try:
                import win32clipboard

                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()

                # BMPフォーマットでクリップボードに保存
                bmp_output = io.BytesIO()
                image.save(bmp_output, format="BMP")
                bmp_data = bmp_output.getvalue()[14:]  # BMPヘッダーを除去

                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
                win32clipboard.CloseClipboard()

                if parent_window:
                    messagebox.showinfo(
                        "コピー完了",
                        "画像をクリップボードにコピーしました",
                        parent=parent_window,
                    )
                return True

            except ImportError:
                # win32clipboardが利用できない場合
                return ClipboardManager.copy_text_to_clipboard(
                    str(image_path),
                    parent_window,
                    "画像の直接コピーができませんでした。\nファイルパスをクリップボードにコピーしました。",
                )

        except Exception as e:
            if parent_window:
                messagebox.showerror("エラー", f"画像のコピーに失敗しました: {e}")
            return False

    @staticmethod
    def copy_text_to_clipboard(
        text: str, parent_window=None, success_message: str = None
    ) -> bool:
        """テキストをクリップボードにコピー"""
        try:
            if parent_window:
                parent_window.clipboard_clear()
                parent_window.clipboard_append(text)
            else:
                # 親ウィンドウがない場合の処理
                import tkinter as tk

                root = tk.Tk()
                root.withdraw()
                root.clipboard_clear()
                root.clipboard_append(text)
                root.update()
                root.destroy()

            if parent_window and success_message:
                messagebox.showinfo("コピー完了", success_message, parent=parent_window)

            return True

        except Exception as e:
            if parent_window:
                messagebox.showerror("エラー", f"テキストのコピーに失敗しました: {e}")
            return False

    @staticmethod
    def open_file_with_default_app(file_path: Path, parent_window=None) -> bool:
        """デフォルトアプリケーションでファイルを開く"""
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(file_path)
            elif system == "Darwin":  # macOS
                os.system(f"open '{file_path}'")
            else:  # Linux
                os.system(f"xdg-open '{file_path}'")
            return True

        except Exception as e:
            if parent_window:
                messagebox.showerror("エラー", f"ファイルを開けませんでした: {e}")
            return False
