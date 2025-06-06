from pathlib import Path

import customtkinter as ctk
from db.models import ImageEntry
from gui.base import BaseToplevel
from gui.components.button import create_delete_button, create_favorite_button
from utils.image import image_manager


class Original(BaseToplevel):
    def __init__(
        self, parent, entry: ImageEntry, tags, is_fav, toggle_fav_cb, delete_cb
    ):
        super().__init__(parent)
        self.title(Path(entry.image_path).name)

        # メイン横並び
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True)

        # ---------------- 左: 画像 ----------------
        left_frame = ctk.CTkFrame(container, fg_color="transparent")
        left_frame.pack(side="left", fill="y", padx=10, pady=10)

        image_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        image_frame.pack()

        label = image_manager.load_full_image(image_frame, entry.image_path)
        label.pack(anchor="w")

        fav_button = create_favorite_button(
            image_frame,
            is_fav,
            command=lambda: toggle_fav_cb(entry.id, fav_button),
        )
        fav_button.place(relx=1.0, rely=1.0, anchor="se", x=-12, y=-12)

        create_delete_button(
            image_frame,
            command=lambda: delete_cb(entry.id, self),
        ).place(relx=0.0, rely=1.0, anchor="sw", x=12, y=-12)

        # ---------------- 右: タグ + ギャラリー ----------------
        right_frame = ctk.CTkFrame(container)
        right_frame.pack(side="left", fill="both", expand=True, padx=(10, 10), pady=10)

        tag_label = ctk.CTkLabel(right_frame, text=" ".join(tags), wraplength=600)
        tag_label.pack(anchor="w", padx=10, pady=(0, 10))

        # ギャラリー用Canvas + Scrollbar
        canvas_container = ctk.CTkFrame(right_frame)
        canvas_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        canvas = ctk.CTkCanvas(canvas_container, highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)

        scrollbar = ctk.CTkScrollbar(
            canvas_container, orientation="vertical", command=canvas.yview
        )
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)

        # 内部スクロール可能なフレーム
        scrollable_frame = ctk.CTkFrame(canvas)
        window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        # スクロール領域の更新
        def on_configure(_):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(window_id, width=canvas.winfo_width())

        scrollable_frame.bind("<Configure>", on_configure)
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width)
        )

        # --- マウスホイールのバインド
        self.enable_mousewheel_scroll(canvas)

        # ダミーのサムネイルを追加
        for i in range(30):
            thumb = ctk.CTkLabel(scrollable_frame, text=f"Thumb {i + 1}", anchor="w")
            thumb.pack(padx=10, pady=5, anchor="w")
