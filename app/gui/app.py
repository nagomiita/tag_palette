from pathlib import Path

import customtkinter as ctk
from config import THUMBNAIL_SIZE
from db.query import (
    get_all_image_entries,
    get_favorite_image_entries,
    get_image_entry_by_id,
)
from gui.base import BaseToplevel, BaseWindow
from gui.components.button import (
    create_delete_button,
    create_favorite_button,
    create_toggle_favorites_button,
)
from gui.thumbnail import ImageThumbnail
from utils.image import load_full_image


class App(BaseWindow):
    def __init__(self):
        super().__init__()
        self.title("Tag Palette")
        self.thumbnail_size = THUMBNAIL_SIZE
        self.image_frames = []
        self.current_columns = 5
        self.show_favorites_only = False

        self._setup_toggle_button()
        self._setup_gallery_canvas()
        self.bind("<Configure>", self._on_resize)

    def _setup_toggle_button(self):
        self.toggle_button = create_toggle_favorites_button(
            self, self.show_favorites_only, self._toggle_favorites
        )
        self.toggle_button.pack(pady=(10, 0), padx=10, anchor="nw")

    def _setup_gallery_canvas(self):
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
        for f in self.image_frames:
            f.destroy()
        self.image_frames.clear()
        w = self.winfo_width()
        columns = max(1, w // (self.thumbnail_size[0] + 20))
        self.current_columns = columns
        row = col = 0

        entries = (
            get_favorite_image_entries()
            if self.show_favorites_only
            else get_all_image_entries()
        )

        for e in entries:
            f = ctk.CTkFrame(self.gallery_frame)
            f.grid(row=row, column=col, padx=4, pady=4)
            self.image_frames.append(f)
            thumb = ImageThumbnail(
                f,
                e.id,
                Path(e.thumbnail_path),
                self.thumbnail_size,
                self._show_full_image,
            )
            thumb.pack()
            caption = ctk.CTkLabel(f, text=Path(e.image_path).name, font=self.fonts)
            caption.pack()
            col = (col + 1) % columns
            if col == 0:
                row += 1

    def _toggle_favorites(self):
        self.show_favorites_only = not self.show_favorites_only
        self.toggle_button.configure(
            text="すべて表示" if self.show_favorites_only else "お気に入りのみ表示"
        )
        self._load_images()

    def _on_resize(self, _):
        new_cols = max(1, self.winfo_width() // (self.thumbnail_size[0] + 20))
        if new_cols != self.current_columns:
            self._load_images()

    def _show_full_image(self, image_id: int):
        entry = get_image_entry_by_id(image_id)
        if not entry:
            return

        top = BaseToplevel(self)
        top.title(Path(entry.image_path).name)
        container = ctk.CTkFrame(top, fg_color="transparent")
        container.pack(padx=20, pady=20, expand=True)
        label = load_full_image(container, entry.image_path)
        label.pack()
        fav_button = create_favorite_button(container, image_id)
        fav_button.place(relx=1.0, rely=1.0, anchor="se", x=-8, y=-8)
        del_button = create_delete_button(
            container, image_id, refresh_callback=top.destroy
        )
        del_button.place(relx=0.0, rely=1.0, anchor="sw", x=4, y=-4)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(-1 * int(event.delta / 120), "units")

    def _on_mousewheel_linux(self, event):
        self.canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
