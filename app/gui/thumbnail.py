import customtkinter as ctk
from config import SHADOW_OFFSET
from PIL import Image, ImageEnhance, ImageFilter


class ImageThumbnail(ctk.CTkLabel):
    def __init__(self, parent, image_id, image_path, size, click_callback=None):
        super().__init__(parent, text="", fg_color="#333333", corner_radius=10)
        self.image_id = image_id
        self.image_path = image_path
        self.size = size
        self.click_callback = click_callback
        self._hover_photo = None
        self._load_image()
        self._bind_events()

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
            self.configure(image=self._photo)
            hover = ImageEnhance.Brightness(canvas).enhance(0.6)
            self._hover_photo = ctk.CTkImage(light_image=hover, size=self.size)
        except Exception as e:
            print(f"[Error] loading {self.image_path}: {e}")

    def _bind_events(self):
        if self.click_callback:
            self.bind("<Button-1>", lambda e: self.click_callback(self.image_id))
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _):
        self.configure(image=self._hover_photo)

    def _on_leave(self, _):
        self.configure(image=self._photo)
