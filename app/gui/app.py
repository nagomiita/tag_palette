from math import ceil
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
        self.current_columns: int = 5
        self.current_page = 0
        self.page_size = 36
        self.total_pages = 0
        self.image_frames: list[ctk.CTkFrame] = []
        self.entries: list[ImageEntry] = []

        self.viewmodel = GalleryViewModel()

        self._setup_toggle_button()
        self._setup_pagination_controls()
        self._setup_scrollable_canvas()
        self.bind("<Configure>", self._on_resize)

        self._load_images()

    # ---------------- UI SETUP ----------------

    def _setup_toggle_button(self):
        self.toggle_button = create_toggle_favorites_button(
            self, self.viewmodel.show_favorites_only, self._on_toggle_favorites
        )
        self.toggle_button.pack(pady=(10, 0), padx=10, anchor="nw")

    def _setup_pagination_controls(self):
        self.pagination_frame = ctk.CTkFrame(self)
        self.pagination_frame.pack(side="bottom", pady=10)

        self.prev_button = ctk.CTkButton(
            self.pagination_frame, text="< Prev", command=self._prev_page
        )
        self.page_entry = ctk.CTkEntry(self.pagination_frame, width=40)
        self.page_entry.bind("<Return>", self._go_to_page)

        self.total_label = ctk.CTkLabel(self.pagination_frame, text="/ ?")
        self.next_button = ctk.CTkButton(
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

        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux)
        self.gallery_frame = ctk.CTkFrame(self.canvas, fg_color="#222222")
        self.canvas.create_window((0, 0), window=self.gallery_frame, anchor="nw")

        self.gallery_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

    # ---------------- IMAGE LOADING ----------------

    def _load_images(self):
        self.entries = self.viewmodel.get_entries()
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
        if not entry:
            return

        top = BaseToplevel(self)
        top.title(Path(entry.image_path).name)

        container = ctk.CTkFrame(top, fg_color="transparent")
        container.pack(padx=20, pady=20, expand=True)

        label = load_full_image(container, entry.image_path)
        label.pack()

        is_fav = self.viewmodel.get_favorite_state(image_id)
        fav_button = create_favorite_button(
            container,
            is_fav,
            command=lambda: self._toggle_favorite(image_id, fav_button),
        )
        fav_button.place(relx=1.0, rely=1.0, anchor="se", x=-8, y=-8)

        create_delete_button(
            container,
            command=lambda: self._on_delete(image_id, top),
        ).place(relx=0.0, rely=1.0, anchor="sw", x=4, y=-4)

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

    def _on_toggle_favorites(self):
        self.viewmodel.toggle_favorites()
        self.toggle_button.configure(
            text="すべて表示"
            if self.viewmodel.show_favorites_only
            else "お気に入りのみ表示"
        )
        self.current_page = 0
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

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(-1 * int(event.delta / 120), "units")

    def _on_mousewheel_linux(self, event):
        self.canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
