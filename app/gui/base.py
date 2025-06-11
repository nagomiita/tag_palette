import platform
import tkinter as tk

import customtkinter as ctk
from config import FONT_SIZE, FONT_TYPE, MARGIN


def maximize_window(window: ctk.CTk | ctk.CTkToplevel, margin=MARGIN):
    if platform.system() == "Windows":
        window.state("zoomed")
    else:
        w, h = window.winfo_screenwidth(), window.winfo_screenheight()
        window.geometry(f"{w}x{h}+{margin}+{margin}")


class WindowBaseMixin:
    def apply_common_style(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.fonts = (FONT_TYPE, FONT_SIZE)
        self.configure(fg_color="#222222")
        self.after(0, lambda: maximize_window(self))

    def get_theme_colors(self):
        """CustomTkinterのテーマカラーを取得"""
        if ctk.get_appearance_mode() == "Dark":
            return {
                "bg_color": "#2b2b2b",
                "fg_color": "#ffffff",
                "select_color": "#1f6aa5",
                "hover_color": "#124c86",
                "frame_color": "#3a3a3a",
                "button_color": "#1f6aa5",
                "button_hover": "#124c86",
                "entry_color": "#343638",
                "text_color": "#ffffff",
                "disabled_color": "#6b6b6b",
            }
        else:
            return {
                "bg_color": "#ffffff",
                "fg_color": "#000000",
                "select_color": "#cce7ff",
                "hover_color": "#b3d9ff",
                "frame_color": "#f0f0f0",
                "button_color": "#1f6aa5",
                "button_hover": "#124c86",
                "entry_color": "#ffffff",
                "text_color": "#000000",
                "disabled_color": "#a0a0a0",
            }

    def get_menu_colors(self):
        """メニュー専用のカラーセット（tkinter使用時のため）"""
        colors = self.get_theme_colors()
        return {
            "bg_color": colors["bg_color"],
            "fg_color": colors["fg_color"],
            "select_color": colors["select_color"],
        }

    def create_styled_menu(self, parent=None):
        """スタイリングされたtk.Menuを作成"""

        colors = self.get_menu_colors()

        menu = tk.Menu(
            parent or self,
            tearoff=0,
            bg=colors["bg_color"],
            fg=colors["fg_color"],
            activebackground=colors["select_color"],
            activeforeground=colors["fg_color"],
            font=("Segoe UI", 10),
        )
        return menu

    def show_styled_menu(self, menu: tk.Menu, event):
        """スタイリングされたメニューを表示"""
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def create_context_menu(self, commands_dict: dict):
        """コンテキストメニューを簡単に作成

        Args:
            commands_dict: {ラベル: コマンド関数} の辞書
                         セパレーターは "---" というキーで指定

        Returns:
            設定済みのtk.Menuオブジェクト
        """
        menu = self.create_styled_menu()

        for label, command in commands_dict.items():
            if label == "---":
                menu.add_separator()
            else:
                menu.add_command(label=label, command=command)

        return menu

    def enable_mousewheel_scroll(self, canvas: ctk.CTkCanvas):
        """
        OSに応じてcanvasにマウスホイールスクロールをバインドする。
        """

        def on_mousewheel(event):
            canvas.yview_scroll(-int(event.delta / 120), "units")

        def on_enter(_):
            if platform.system() == "Linux":
                canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
                canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
            else:
                canvas.bind_all("<MouseWheel>", on_mousewheel)

        def on_leave(_):
            if platform.system() == "Linux":
                canvas.unbind("<Button-4>")
                canvas.unbind("<Button-5>")
            else:
                canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", on_enter)
        canvas.bind("<Leave>", on_leave)


class BaseWindow(ctk.CTk, WindowBaseMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_style()


class BaseToplevel(ctk.CTkToplevel, WindowBaseMixin):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.attributes("-topmost", True)
        self.apply_common_style()
