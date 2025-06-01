import customtkinter as ctk
from config import SHADOW_OFFSET
from gui.components.button import create_delete_button, create_favorite_button
from utils.image import generate_thumbnail_images


class ImageThumbnail(ctk.CTkFrame):
    def __init__(self, parent, image_id, image_path, size, click_callback=None):
        super().__init__(parent, fg_color="#333333", corner_radius=10)
        self.image_id = image_id
        self.image_path = image_path
        self.size = size
        self.click_callback = click_callback
        self._photo = None
        self._hover_photo = None

        self._setup_widgets()
        self._setup_buttons()
        self._bind_events()

    def _setup_widgets(self):
        self.label = ctk.CTkLabel(self, text="")
        self.label.pack()
        self._load_image()

    def _setup_buttons(self):
        create_favorite_button(self, self.image_id).place(
            relx=1.0, rely=1.0, anchor="se", x=-4, y=-4
        )
        create_delete_button(
            self, self.image_id, refresh_callback=self._delete_thumbnail
        ).place(relx=0.0, rely=1.0, anchor="sw", x=4, y=-4)

    def _bind_events(self):
        if self.click_callback:
            self.label.bind("<Button-1>", lambda e: self.click_callback(self.image_id))
        self.label.bind("<Enter>", self._on_enter)
        self.label.bind("<Leave>", self._on_leave)

    def _load_image(self):
        try:
            self._photo, self._hover_photo = generate_thumbnail_images(
                self.image_path, self.size, SHADOW_OFFSET
            )
            self.label.configure(image=self._photo)
        except Exception as e:
            print(f"[Error] loading {self.image_path}: {e}")

    def _on_enter(self, _):
        if self._hover_photo:
            self.label.configure(image=self._hover_photo)

    def _on_leave(self, _):
        if self._photo:
            self.label.configure(image=self._photo)

    def _delete_thumbnail(self):
        self.destroy()
