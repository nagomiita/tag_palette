from pathlib import Path

import customtkinter
from PIL import Image, ImageEnhance, ImageFilter

# --- 定数設定 ---
FONT_TYPE = "meiryo"
IMAGE_DIR = Path("images")
THUMBNAIL_SIZE = (150, 150)
MAX_COLUMNS = 5


# --- ImageThumbnail クラス ---
class ImageThumbnail(customtkinter.CTkLabel):
    def __init__(self, parent, image_path, size=(150, 150), click_callback=None):
        self.image_path = image_path
        self.size = size
        self.click_callback = click_callback
        self._hover_photo = None

        super().__init__(parent, text="", fg_color="#333333", corner_radius=10)

        self.load_image()

        if click_callback:
            self.bind("<Button-1>", lambda e: click_callback(image_path))

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def load_image(self):
        try:
            img = Image.open(self.image_path)
            img.thumbnail(self.size, Image.Resampling.LANCZOS)

            canvas_size = self.size
            canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            x = (canvas_size[0] - img.width) // 2
            y = (canvas_size[1] - img.height) // 2
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            canvas.paste(img, (x, y), img)

            shadow = canvas.copy().filter(ImageFilter.GaussianBlur(2))
            final_img = Image.new(
                "RGBA", (canvas_size[0] + 4, canvas_size[1] + 4), (0, 0, 0, 0)
            )
            final_img.paste(shadow, (2, 2), shadow)
            final_img.paste(canvas, (0, 0), canvas)

            self._photo = customtkinter.CTkImage(light_image=final_img, size=self.size)
            self.configure(image=self._photo)

            hover_img = canvas.copy()
            hover_img = ImageEnhance.Brightness(hover_img).enhance(0.6)
            self._hover_photo = customtkinter.CTkImage(
                light_image=hover_img, size=self.size
            )

        except Exception as e:
            print(f"Failed to load {self.image_path}: {e}")
            placeholder = Image.new("RGBA", self.size, (80, 80, 80))
            self._photo = customtkinter.CTkImage(
                light_image=placeholder, size=self.size
            )
            self.configure(image=self._photo)

    def _on_enter(self, event):
        if self._hover_photo:
            self.configure(image=self._hover_photo)

    def _on_leave(self, event):
        self.configure(image=self._photo)


# --- アプリケーション本体 ---
class App(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        self.fonts = (FONT_TYPE, 13)
        self.geometry("1000x700")
        self.title("フォトギャラリー")
        customtkinter.set_appearance_mode("dark")
        customtkinter.set_default_color_theme("blue")

        self.thumbnail_size = THUMBNAIL_SIZE
        self.image_frames = []
        self.current_columns = 5

        self.setup_scrollable_gallery()

        # リサイズイベント登録
        self.bind("<Configure>", self.on_resize)

    def setup_scrollable_gallery(self):
        self.canvas = customtkinter.CTkCanvas(self, background="#222222")
        self.scrollbar = customtkinter.CTkScrollbar(
            self, orientation="vertical", command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.gallery_frame = customtkinter.CTkFrame(self.canvas, fg_color="#222222")
        self.gallery_frame_id = self.canvas.create_window(
            (0, 0), window=self.gallery_frame, anchor="nw"
        )
        self.gallery_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        self.load_images()

    def load_images(self):
        for frame in self.image_frames:
            frame.destroy()
        self.image_frames.clear()

        gallery_width = self.winfo_width()
        thumb_w = self.thumbnail_size[0] + 40
        columns = max(1, gallery_width // thumb_w)
        self.current_columns = columns

        row = col = 0
        for img_path in sorted(IMAGE_DIR.glob("*")):
            if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp", ".gif"):
                continue

            frame = customtkinter.CTkFrame(self.gallery_frame)
            frame.grid(row=row, column=col, padx=10, pady=10)
            self.image_frames.append(frame)

            thumb = ImageThumbnail(frame, image_path=img_path, size=self.thumbnail_size)
            thumb.pack()

            caption = customtkinter.CTkLabel(frame, text=img_path.name, font=self.fonts)
            caption.pack()

            col += 1
            if col >= columns:
                col = 0
                row += 1

    def on_resize(self, event):
        # 以前の列数と異なるなら再描画
        gallery_width = self.winfo_width()
        new_columns = max(1, gallery_width // (self.thumbnail_size[0] + 40))
        if new_columns != self.current_columns:
            self.load_images()


# --- 実行 ---
if __name__ == "__main__":
    app = App()
    app.mainloop()
