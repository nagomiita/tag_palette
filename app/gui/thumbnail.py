import customtkinter as ctk
from config import SHADOW_OFFSET
from db.query import get_favorite_flag, toggle_favorite_flag
from utils.image import generate_thumbnail_images


class ImageThumbnail(ctk.CTkFrame):
    def __init__(self, parent, image_id, image_path, size, click_callback=None):
        super().__init__(parent, fg_color="#333333", corner_radius=10)
        self.image_id = image_id
        self.image_path = image_path
        self.size = size
        self.click_callback = click_callback
        self._hover_photo = None

        self.label = ctk.CTkLabel(self, text="")
        self.label.pack()
        self._load_image()
        self._bind_events()

        self.is_fav = get_favorite_flag(self.image_id)
        self.favorite_button = ctk.CTkButton(
            self,
            text="♥" if self.is_fav else "♡",
            fg_color="#ff9eb5" if self.is_fav else "#1f6aa5",
            width=30,
            height=30,
            font=("Arial", 24),
            command=self.toggle_favorite,
        )
        self.favorite_button.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-4)

    def _load_image(self):
        try:
            self._photo, self._hover_photo = generate_thumbnail_images(
                self.image_path, self.size, SHADOW_OFFSET
            )
            self.label.configure(image=self._photo)
        except Exception as e:
            print(f"[Error] loading {self.image_path}: {e}")

    def _bind_events(self):
        if self.click_callback:
            self.label.bind("<Button-1>", lambda e: self.click_callback(self.image_id))
        self.label.bind("<Enter>", self._on_enter)
        self.label.bind("<Leave>", self._on_leave)

    def _on_enter(self, _):
        self.label.configure(image=self._hover_photo)

    def _on_leave(self, _):
        self.label.configure(image=self._photo)

    def toggle_favorite(self):
        is_fav = toggle_favorite_flag(self.image_id)
        if is_fav is not None:
            self.is_fav = is_fav
            self.favorite_button.configure(
                text="♥" if self.is_fav else "♡",
                fg_color="#ff9eb5" if self.is_fav else "#1f6aa5",
            )
