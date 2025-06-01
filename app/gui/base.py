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
