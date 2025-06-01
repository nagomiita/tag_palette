import customtkinter as ctk
from config import SHADOW_OFFSET
from PIL import Image, ImageEnhance, ImageFilter


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

        self.favorite_button = ctk.CTkButton(
            self,
            text="♡",  # 非お気に入り：♡, お気に入り：♥
            width=20,
            height=20,
            font=("Arial", 14),
            command=self.toggle_favorite,
        )
        self.favorite_button.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-4)

    def _load_image(self):
        try:
            img = Image.open(self.image_path)
            img.thumbnail(self.size, Image.Resampling.LANCZOS)
            img = img.convert("RGBA")
            canvas = Image.new("RGBA", self.size, (0, 0, 0, 0))
            x = (self.size[0] - img.width) // 2
            y = (self.size[1] - img.height) // 2
            canvas.paste(img, (x, y), img)
            shadow = canvas.copy().filter(ImageFilter.GaussianBlur(2))
            final_img = Image.new(
                "RGBA",
                (self.size[0] + SHADOW_OFFSET, self.size[1] + SHADOW_OFFSET),
                (0, 0, 0, 0),
            )
            final_img.paste(shadow, (2, 2), shadow)
            final_img.paste(canvas, (0, 0), canvas)
            self._photo = ctk.CTkImage(light_image=final_img, size=self.size)
            self.label.configure(image=self._photo)
            hover = ImageEnhance.Brightness(canvas).enhance(0.6)
            self._hover_photo = ctk.CTkImage(light_image=hover, size=self.size)
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
        from db.init import engine
        from db.models import ImageEntry
        from sqlalchemy.orm import Session

        with Session(engine) as session:
            entry = (
                session.query(ImageEntry).filter(ImageEntry.id == self.image_id).first()
            )
            if entry:
                entry.is_favorite = not entry.is_favorite
                session.commit()
                self.favorite_button.configure(text="♥" if entry.is_favorite else "♡")
