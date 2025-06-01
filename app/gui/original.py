from pathlib import Path

import customtkinter as ctk
from db.models import ImageEntry
from gui.base import BaseToplevel
from gui.components.button import create_delete_button, create_favorite_button
from utils.image import load_full_image


class Original(BaseToplevel):
    def __init__(
        self, parent, entry: ImageEntry, tags, is_fav, toggle_fav_cb, delete_cb
    ):
        super().__init__(parent)
        self.title(Path(entry.image_path).name)

        # 横並びのメインフレーム
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(expand=True, fill="both", padx=0, pady=0)

        # ===== 左側: 画像エリア =====
        left_frame = ctk.CTkFrame(container, fg_color="transparent")
        left_frame.pack(side="left", fill="y", padx=10, pady=10)

        image_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        image_frame.pack()

        label = load_full_image(image_frame, entry.image_path)
        label.pack(anchor="w")

        # ボタンを画像の下部に重ねて表示
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

        # ===== 右側: タグ + ギャラリーエリア =====
        right_frame = ctk.CTkFrame(container, fg_color="#2a2a2a")
        right_frame.pack(side="left", expand=True, fill="both", padx=(10, 10), pady=10)

        # タグ表示（上部）
        tag_label = ctk.CTkLabel(right_frame, text=" ".join(tags), wraplength=600)
        tag_label.pack(anchor="w", padx=10, pady=(0, 10))

        # ギャラリー領域（下部）
        gallery_frame = ctk.CTkFrame(right_frame, fg_color="#3a3a3a")
        gallery_frame.pack(expand=True, fill="both", padx=10)

        for i in range(10):
            thumb = ctk.CTkLabel(gallery_frame, text=f"Thumb {i + 1}")
            thumb.pack(pady=5, padx=10, anchor="w")
