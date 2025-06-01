import customtkinter as ctk
from config import SHADOW_OFFSET
from gui.components.button import create_delete_button, create_favorite_button
from gui.viewmodel import ImageThumbnailViewModel
from utils.image import load_thumbnail_image


class ImageThumbnail(ctk.CTkFrame):
    def __init__(self, parent, image_id, image_path, size, click_callback=None):
        super().__init__(parent, fg_color="#333333", corner_radius=10)
        self.image_id = image_id
        self.image_path = image_path
        self.size = size
        self.click_callback = click_callback
        self._photo = None
        self._hover_photo = None

        self.viewmodel = ImageThumbnailViewModel(self.image_id, self.image_path)

        self._setup_widgets()
        self._setup_buttons()
        self._bind_events()

    def _setup_widgets(self):
        self.label = ctk.CTkLabel(self, text="")
        self.label.pack()
        self._load_image()

    def _setup_buttons(self):
        is_fav = self.viewmodel.get_favorite_state()
        self.favorite_button = create_favorite_button(
            self, is_fav, self._toggle_favorite
        )
        self.favorite_button.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-4)

        delete_button = create_delete_button(self, self._on_delete)
        delete_button.place(relx=0.0, rely=1.0, anchor="sw", x=4, y=-4)

    def _bind_events(self):
        if self.click_callback:
            self.label.bind("<Button-1>", lambda e: self.click_callback(self.image_id))
        self.label.bind("<Enter>", self._on_enter)
        self.label.bind("<Leave>", self._on_leave)

    def _load_image(self):
        try:
            self._photo, self._hover_photo = load_thumbnail_image(
                str(self.image_path), self.size, SHADOW_OFFSET
            )
            if self._photo:
                self.label.configure(image=self._photo)
        except Exception as e:
            print(f"[Error] loading {self.image_path}: {e}")

    def _on_enter(self, _):
        if self._hover_photo:
            self.label.configure(image=self._hover_photo)

    def _on_leave(self, _):
        if self._photo:
            self.label.configure(image=self._photo)

    def _on_delete(self):
        success = self.viewmodel.delete_image()
        if success:
            self.destroy()

    def _toggle_favorite(self):
        new_state = self.viewmodel.toggle_favorite()
        if new_state is not None:
            self.favorite_button.configure(
                text="♥" if new_state else "♡",
                fg_color="#ff9eb5" if new_state else "#1f6aa5",
                hover_color="#c268a7" if new_state else "#124c86",
            )
