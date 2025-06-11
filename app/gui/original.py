from pathlib import Path

import customtkinter as ctk
from db.models import ImageEntry
from gui.base import BaseToplevel
from gui.components.button import create_delete_button, create_favorite_button
from utils.file_operations import FileOperationManager
from utils.image import image_manager


class Original(BaseToplevel):
    def __init__(
        self,
        parent,
        entry: ImageEntry,
        tags,
        is_fav,
        toggle_fav_cb,
        delete_cb,
        show_similar_images_cb=None,
    ):
        super().__init__(parent)
        self.lift()
        self.attributes("-topmost", True)
        self.after(100, lambda: self.attributes("-topmost", False))  # 一度解除
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

        # 画像にコピー機能を追加
        self.entry = entry
        self.file_ops = FileOperationManager(self)
        self._setup_image_copy(label)

        fav_button = create_favorite_button(
            image_frame,
            is_fav,
            command=lambda: toggle_fav_cb(entry.id, fav_button),
        )
        fav_button.place(relx=1.0, rely=1.0, anchor="se", x=-12, y=-12)
        if not is_fav:
            del_button = create_delete_button(
                image_frame,
                command=lambda: delete_cb(entry.id, self),
            )
            del_button.place(relx=0.0, rely=1.0, anchor="sw", x=12, y=-12)

        # ---------------- 右: タグ + ギャラリー ----------------
        right_frame = ctk.CTkFrame(container)
        right_frame.pack(side="left", fill="both", expand=True, padx=(10, 10), pady=10)

        # タグラベル作成（初期値は仮で600）
        tag_label = ctk.CTkLabel(right_frame, text=" ".join(tags), wraplength=600)
        tag_label.pack(anchor="w", padx=10, pady=(0, 10))

        # 幅に合わせてwraplengthを更新
        def update_wraplength(event):
            new_width = event.width - 20  # パディング分を考慮
            tag_label.configure(wraplength=max(100, new_width))  # 最小幅100で制限

        right_frame.bind("<Configure>", update_wraplength)

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

        if show_similar_images_cb:
            scrollable_frame.after(
                100, lambda: show_similar_images_cb(entry, scrollable_frame)
            )

    def _setup_image_copy(self, widget: ctk.CTkLabel):
        """使用例：簡単なコンテキストメニュー設定"""
        menu = self.create_context_menu(
            {
                "画像をコピー": lambda: self.file_ops.copy_image(self.entry.image_path),
                "ファイルパスをコピー": lambda: self.file_ops.copy_file_path(
                    self.entry.image_path
                ),
                "---": None,
                "ファイルを開く": lambda: self.file_ops.open_file(
                    self.entry.image_path
                ),
            }
        )

        widget.bind("<Button-3>", lambda e: self.show_styled_menu(menu, e))
        widget.bind(
            "<Control-c>", lambda e: self.file_ops.copy_image(self.entry.image_path)
        )
        widget.focus_set()
