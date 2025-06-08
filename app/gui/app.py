from math import ceil
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
from config import THUMBNAIL_SIZE
from db.models import ImageEntry
from gui.base import BaseWindow
from gui.components.button import create_button
from gui.original import Original
from gui.thumbnail import ImageThumbnail
from gui.viewmodel import GalleryViewModel
from utils.image import image_manager
from utils.logger import setup_logging
from utils.pose import search_top_similar_pose_ids

logger = setup_logging()


class App(BaseWindow):
    def __init__(self):
        super().__init__()
        self.title("Tag Palette")
        self.thumbnail_size = THUMBNAIL_SIZE
        self.current_columns: int = 5
        self.current_page = 0
        self.page_size = 36
        self.total_pages = 0
        self.image_frames: list[ctk.CTkFrame] = []
        self.entries: list[ImageEntry] = []

        self.viewmodel = GalleryViewModel()

        self._setup_header_buttons()
        self._setup_pagination_controls()
        self._setup_scrollable_canvas()
        self.bind("<Configure>", self._on_resize)

        self._load_images()

    # ---------------- UI SETUP ----------------

    def _setup_header_buttons(self):
        button_frame = ctk.CTkFrame(self)
        button_frame.pack(pady=(10, 0), padx=10, anchor="nw")

        self.add_button = create_button(
            parent=button_frame,
            text="＋ 新規追加",
            command=self._on_add_images,
            fg_color="#33aa77",
            hover_color="#1e6144",
        )
        self.add_button.pack(side="left", padx=(0, 10))

        self.toggle_button = create_button(
            parent=button_frame,
            text="すべて表示" if self.viewmodel.show_favorites_only else "♡のみ表示",
            command=self._on_toggle_favorites,
            fg_color="#eb4f74",
            hover_color="#af3d57",
        )
        self.toggle_button.pack(side="left", padx=(0, 10))

        self.sensitive_toggle_button = create_button(
            parent=button_frame,
            text="Sを非表示" if self.viewmodel.show_sensitive else "Sを表示",
            command=self._on_toggle_sensitive,
            fg_color="#a370f7",
            hover_color="#6c4fc2",
        )
        self.sensitive_toggle_button.pack(side="left")

    def _setup_pagination_controls(self):
        self.pagination_frame = ctk.CTkFrame(self)
        self.pagination_frame.pack(side="bottom", pady=10)

        self.prev_button = create_button(
            self.pagination_frame, text="< Prev", command=self._prev_page
        )
        self.page_entry = ctk.CTkEntry(self.pagination_frame, width=40)
        self.page_entry.bind("<Return>", self._go_to_page)

        self.total_label = ctk.CTkLabel(self.pagination_frame, text="/ ?")
        self.next_button = create_button(
            self.pagination_frame, text="Next >", command=self._next_page
        )

        self.prev_button.pack(side="left", padx=10)
        self.page_entry.pack(side="left")
        self.total_label.pack(side="left", padx=(2, 10))
        self.next_button.pack(side="left")

    def _setup_scrollable_canvas(self):
        self.canvas = ctk.CTkCanvas(self, background="#222222", highlightthickness=0)
        self.scrollbar = ctk.CTkScrollbar(
            self, orientation="vertical", command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.gallery_frame = ctk.CTkFrame(self.canvas, fg_color="#222222")
        self.canvas.create_window((0, 0), window=self.gallery_frame, anchor="nw")

        self.gallery_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.enable_mousewheel_scroll(self.canvas)

    # ---------------- IMAGE LOADING ----------------

    def _load_images(self):
        self.entries = self.viewmodel.get_entries(
            favorites_only=self.viewmodel.show_favorites_only,
            include_sensitive=self.viewmodel.show_sensitive,
        )
        self.total_pages = ceil(len(self.entries) / self.page_size)
        self.current_columns = self._calculate_columns()
        self._draw_page()

    def _draw_page(self):
        self._clear_gallery()

        start = self.current_page * self.page_size
        end = start + self.page_size
        page_entries = self.entries[start:end]

        row = col = 0
        for entry in page_entries:
            frame = self._create_thumbnail_frame(entry)
            frame.grid(row=row, column=col, padx=8, pady=4)
            self.image_frames.append(frame)
            col = (col + 1) % self.current_columns
            if col == 0:
                row += 1

        self.page_entry.delete(0, "end")
        self.page_entry.insert(0, str(self.current_page + 1))
        self.prev_button.configure(
            state="disabled" if self.current_page == 0 else "normal"
        )
        self.next_button.configure(
            state="disabled" if self.current_page >= self.total_pages - 1 else "normal"
        )
        self.total_label.configure(text=f"/ {self.total_pages}")

    def _clear_gallery(self):
        for frame in self.image_frames:
            frame.destroy()
        self.image_frames.clear()

    def _create_thumbnail_frame(self, entry: ImageEntry):
        frame = ctk.CTkFrame(self.gallery_frame)
        thumb = ImageThumbnail(
            frame,
            entry.id,
            Path(entry.thumbnail_path),
            self.thumbnail_size,
            self._show_full_image,
        )
        thumb.pack()

        caption = ctk.CTkLabel(frame, text=Path(entry.image_path).name, font=self.fonts)
        caption.pack()

        return frame

    def _calculate_columns(self):
        width = self.winfo_width()
        return max(1, width // (self.thumbnail_size[0] + 20))

    # ---------------- FULL VIEW ----------------

    def _show_full_image(self, image_id: int):
        entry = self.viewmodel.get_image_by_id(image_id)
        if not Path(entry.image_path).exists():
            messagebox.showerror(
                "エラー", f"画像が見つかりませんでした。\n{entry.image_path}"
            )
            return

        tags = self.viewmodel.get_tags_for_image(image_id)
        is_fav = self.viewmodel.get_favorite_state(image_id)

        Original(
            parent=self,
            entry=entry,
            tags=tags,
            is_fav=is_fav,
            toggle_fav_cb=self._toggle_favorite,
            delete_cb=self._on_delete,
            show_similar_images_cb=self.show_similar_images,
        )

    def show_similar_images(
        self, base_entry: ImageEntry, parent_frame: ctk.CTkFrame, top_k=30
    ):
        query_vec = self.viewmodel.get_image_tag_embedding(base_entry.id)
        if query_vec is None:
            logger.warning("❌ クエリ画像のベクトルがありません")
            return

        db_vectors = self.viewmodel.load_all_image_tag_embedding(base_entry.id)
        top_ids = search_top_similar_pose_ids(query_vec, db_vectors, top_k=top_k)

        # 1. フレームの幅を取得（更新を確実に反映させるために update を呼ぶ）
        parent_frame.update_idletasks()
        frame_width = parent_frame.winfo_width()

        # 2. サムネイルサイズと余白から1行の表示可能数を計算
        thumb_width = 150 + 5 * 2  # 幅 + padx左右
        max_columns = max(1, frame_width // thumb_width)

        for idx, image_id in enumerate(top_ids):
            entry = self.viewmodel.get_image_by_id(image_id)
            thumb = ImageThumbnail(
                parent_frame,
                entry.id,
                Path(entry.thumbnail_path),
                size=(150, 150),
                click_callback=self._show_full_image,
            )
            row = idx // max_columns
            col = idx % max_columns
            thumb.grid(row=row, column=col, padx=10, pady=10)

    def _toggle_favorite(self, image_id: int, button: ctk.CTkButton):
        new_state = self.viewmodel.toggle_favorite(image_id)
        if new_state is not None:
            button.configure(
                text="♥" if new_state else "♡",
                fg_color="#ff9eb5" if new_state else "#1f6aa5",
                hover_color="#c268a7" if new_state else "#124c86",
            )

    def _on_delete(self, image_id: int, toplevel: ctk.CTkToplevel):
        if self.viewmodel.delete_image(image_id):
            toplevel.destroy()
            self._load_images()

    # ---------------- EVENTS ----------------
    def _on_add_images(self):
        image_manager.register_new_images(is_first_run=False)
        self._load_images()

    def _on_toggle_favorites(self):
        self.viewmodel.toggle_favorites()
        self.toggle_button.configure(
            text="すべて表示" if self.viewmodel.show_favorites_only else "♡のみ表示"
        )
        self.current_page = 0
        self._load_images()

    def _on_toggle_sensitive(self):
        self.viewmodel.toggle_sensitive()
        self.sensitive_toggle_button.configure(
            text="🔞を非表示" if self.viewmodel.show_sensitive else "🔞を表示"
        )
        self._load_images()

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._draw_page()

    def _next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._draw_page()

    def _go_to_page(self, _):
        try:
            page = int(self.page_entry.get()) - 1
            if 0 <= page < self.total_pages:
                self.current_page = page
                self._draw_page()
            else:
                print(f"⚠ 範囲外のページ番号: 1〜{self.total_pages}")
        except ValueError:
            print("⚠ 数字を入力してください")

    def _on_resize(self, _):
        new_columns = self._calculate_columns()
        if new_columns != self.current_columns:
            self._load_images()
