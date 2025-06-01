import platform

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


class BaseWindow(ctk.CTk, WindowBaseMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_style()


class BaseToplevel(ctk.CTkToplevel, WindowBaseMixin):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.attributes("-topmost", True)
        self.apply_common_style()
