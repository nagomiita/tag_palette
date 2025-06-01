from pathlib import Path

import customtkinter as ctk
from config import THUMBNAIL_SIZE
from db.models import ImageEntry
from gui.base import BaseToplevel, BaseWindow
from gui.components.button import (
    create_delete_button,
    create_favorite_button,
    create_toggle_favorites_button,
)
from gui.thumbnail import ImageThumbnail
from gui.viewmodel import GalleryViewModel
from utils.image import load_full_image


class App(BaseWindow):
    def __init__(self):
        super().__init__()
        self.title("Tag Palette")
        self.thumbnail_size = THUMBNAIL_SIZE
        self.image_frames: list[ctk.CTkFrame] = []
        self.current_columns: int = 5

        self.viewmodel = GalleryViewModel()

        self._setup_toggle_button()
        self._setup_scrollable_canvas()
        self.bind("<Configure>", self._on_resize)

    def _setup_toggle_button(self):
        self.toggle_button = create_toggle_favorites_button(
            self, self.viewmodel.show_favorites_only, self._on_toggle_favorites
        )
        self.toggle_button.pack(pady=(10, 0), padx=10, anchor="nw")

    def _on_toggle_favorites(self):
        self.viewmodel.toggle_favorites()
        self.toggle_button.configure(
            text="すべて表示"
            if self.viewmodel.show_favorites_only
            else "お気に入りのみ表示"
        )
        self._load_images()

    def _setup_scrollable_canvas(self):
        self.canvas = ctk.CTkCanvas(self, background="#222222")
        self.scrollbar = ctk.CTkScrollbar(
            self, orientation="vertical", command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux)

        self.gallery_frame = ctk.CTkFrame(self.canvas, fg_color="#222222")
        self.canvas.create_window((0, 0), window=self.gallery_frame, anchor="nw")

        self.gallery_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        self._load_images()

    def _load_images(self):
        self._clear_gallery()
        self.current_columns = self._calculate_columns()
        entries = self.viewmodel.get_entries()

        row = col = 0
        for entry in entries:
            frame = self._create_thumbnail_frame(entry)
            frame.grid(row=row, column=col, padx=4, pady=4)
            self.image_frames.append(frame)
            col = (col + 1) % self.current_columns
            if col == 0:
                row += 1

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

    def _clear_gallery(self):
        for frame in self.image_frames:
            frame.destroy()
        self.image_frames.clear()

    def _calculate_columns(self):
        width = self.winfo_width()
        return max(1, width // (self.thumbnail_size[0] + 20))

    def _toggle_favorites(self):
        self.show_favorites_only = not self.show_favorites_only
        new_text = "すべて表示" if self.show_favorites_only else "お気に入りのみ表示"
        self.toggle_button.configure(text=new_text)
        self._load_images()

    def _on_resize(self, _):
        new_columns = self._calculate_columns()
        if new_columns != self.current_columns:
            self._load_images()

    def _show_full_image(self, image_id: int):
        entry = self.viewmodel.get_image_by_id(image_id)
        if not entry:
            return

        top = BaseToplevel(self)
        top.title(Path(entry.image_path).name)

        container = ctk.CTkFrame(top, fg_color="transparent")
        container.pack(padx=20, pady=20, expand=True)

        label = load_full_image(container, entry.image_path)
        label.pack()

        is_fav = self.viewmodel.get_favorite_state(image_id)

        # お気に入りボタン
        self.favorite_button = create_favorite_button(
            container,
            is_fav,
            command=lambda: self._toggle_favorite(image_id),
        )
        self.favorite_button.place(relx=1.0, rely=1.0, anchor="se", x=-8, y=-8)

        # 削除ボタン
        create_delete_button(
            container,
            command=lambda: self._on_delete(image_id, top),
        ).place(relx=0.0, rely=1.0, anchor="sw", x=4, y=-4)

    def _on_delete(self, image_id: int, toplevel: ctk.CTkToplevel):
        success = self.viewmodel.delete_image(image_id)
        if success:
            toplevel.destroy()
            self._load_images()

    def _toggle_favorite(self, image_id: int):
        new_state = self.viewmodel.toggle_favorite(image_id)
        if new_state is not None:
            self.favorite_button.configure(
                text="♥" if new_state else "♡",
                fg_color="#ff9eb5" if new_state else "#1f6aa5",
                hover_color="#c268a7" if new_state else "#124c86",
            )

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(-1 * int(event.delta / 120), "units")

    def _on_mousewheel_linux(self, event):
        self.canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
