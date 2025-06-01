import platform
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageEnhance, ImageFilter
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base

# === 設定 ===
FONT_TYPE = "meiryo"
FONT_SIZE = 13
THUMBNAIL_SIZE = (190, 200)
IMAGE_DIR = Path("images")
SUPPORTED_FORMATS = (".jpg", ".jpeg", ".png", ".bmp", ".gif")
MARGIN = 10
SHADOW_OFFSET = 4


DB_PATH = "data.db"
THUMB_DIR = Path("thumbnails")
THUMB_DIR.mkdir(exist_ok=True)

Base = declarative_base()
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


class ImageEntry(Base):
    __tablename__ = "images"
    id = Column(Integer, primary_key=True)
    image_path = Column(String, nullable=False)
    thumbnail_path = Column(String, nullable=False)


def initialize_database():
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        registered_paths = {
            row.image_path for row in session.query(ImageEntry.image_path).all()
        }

        for img_path in sorted(IMAGE_DIR.glob("*")):
            if img_path.suffix.lower() not in SUPPORTED_FORMATS:
                continue
            if str(img_path) in registered_paths:
                continue

            thumb_path = THUMB_DIR / f"{img_path.stem}_thumb.png"
            img = Image.open(img_path)
            img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            img.save(thumb_path)

            entry = ImageEntry(image_path=str(img_path), thumbnail_path=str(thumb_path))
            session.add(entry)

        session.commit()


# === ヘルパー ===
def maximize_window(window: ctk.CTk | ctk.CTkToplevel, margin: int = MARGIN) -> None:
    if platform.system() == "Windows":
        window.state("zoomed")
    else:
        width = window.winfo_screenwidth()
        height = window.winfo_screenheight()
        window.geometry(f"{width}x{height}+{margin}+{margin}")


# === 共通処理 ===
class WindowBaseMixin:
    def apply_common_style(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.fonts = (FONT_TYPE, FONT_SIZE)
        self.configure(fg_color="#222222")
        self.after(0, lambda: maximize_window(self))


# === ウィンドウ基底クラス ===
class BaseWindow(ctk.CTk, WindowBaseMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_common_style()


class BaseToplevel(ctk.CTkToplevel, WindowBaseMixin):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.attributes("-topmost", True)
        self.apply_common_style()


# === サムネイルラベル ===
class ImageThumbnail(ctk.CTkLabel):
    def __init__(
        self,
        parent,
        image_id: int,
        image_path: Path,
        size=THUMBNAIL_SIZE,
        click_callback=None,
    ):
        super().__init__(parent, text="", fg_color="#333333", corner_radius=10)
        self.image_id = image_id
        self.image_path = image_path
        self.size = size
        self.click_callback = click_callback
        self._hover_photo = None

        self.__load_image()
        self.__bind_events()

    def __load_image(self):
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

            hover_img = ImageEnhance.Brightness(canvas).enhance(0.6)
            self._hover_photo = ctk.CTkImage(light_image=hover_img, size=self.size)

        except Exception as e:
            print(f"[Error] Could not load image {self.image_path}: {e}")
            placeholder = Image.new("RGBA", self.size, (80, 80, 80))
            self._photo = ctk.CTkImage(light_image=placeholder, size=self.size)
            self.configure(image=self._photo)

    def __bind_events(self):
        if self.click_callback:
            self.bind("<Button-1>", lambda e: self.click_callback(self.image_id))
        self.bind("<Enter>", self.__on_enter)
        self.bind("<Leave>", self.__on_leave)

    def __on_enter(self, _):
        if self._hover_photo:
            self.configure(image=self._hover_photo)

    def __on_leave(self, _):
        self.configure(image=self._photo)


# === メインアプリ ===
class App(BaseWindow):
    def __init__(self):
        super().__init__()
        self.title("フォトギャラリー")
        self.thumbnail_size = THUMBNAIL_SIZE
        self.image_frames = []
        self.current_columns = 5

        self.__setup_gallery_canvas()
        self.bind("<Configure>", self.__on_resize)

    def __setup_gallery_canvas(self):
        self.canvas = ctk.CTkCanvas(self, background="#222222")
        self.scrollbar = ctk.CTkScrollbar(
            self, orientation="vertical", command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self.__on_mousewheel)  # Windows/macOS
        self.canvas.bind_all(
            "<Button-4>", self.__on_mousewheel_linux
        )  # Linux 上スクロール
        self.canvas.bind_all(
            "<Button-5>", self.__on_mousewheel_linux
        )  # Linux 下スクロール

        self.gallery_frame = ctk.CTkFrame(self.canvas, fg_color="#222222")
        self.canvas.create_window((0, 0), window=self.gallery_frame, anchor="nw")
        self.gallery_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        self.__load_images()

    def __load_images(self):
        for frame in self.image_frames:
            frame.destroy()
        self.image_frames.clear()

        gallery_width = self.winfo_width()
        thumb_w = self.thumbnail_size[0] + 50
        columns = max(1, gallery_width // thumb_w)
        self.current_columns = columns

        row = col = 0
        with Session(engine) as session:
            for entry in session.query(ImageEntry).order_by(ImageEntry.id).all():
                frame = ctk.CTkFrame(self.gallery_frame)
                frame.grid(row=row, column=col, padx=10, pady=10)
                self.image_frames.append(frame)

                thumb = ImageThumbnail(
                    frame,
                    image_id=entry.id,
                    image_path=Path(entry.thumbnail_path),
                    size=self.thumbnail_size,
                    click_callback=self.__show_full_image,
                )
                thumb.pack()

                caption = ctk.CTkLabel(
                    frame, text=Path(entry.image_path).name, font=self.fonts
                )
                caption.pack()

                col += 1
                if col >= columns:
                    col = 0
                    row += 1

    def __on_resize(self, _):
        new_columns = max(1, self.winfo_width() // (self.thumbnail_size[0] + 50))
        if new_columns != self.current_columns:
            self.__load_images()

    def __show_full_image(self, image_id: int):
        try:
            with Session(engine) as session:
                entry = (
                    session.query(ImageEntry).filter(ImageEntry.id == image_id).first()
                )
                if not entry:
                    print(f"[Error] No image found with ID {image_id}")
                    return

                image_path = Path(entry.image_path)

            top = BaseToplevel(self)
            top.title(image_path.name)

            screen_width = top.winfo_screenwidth()
            screen_height = top.winfo_screenheight()

            img = Image.open(image_path)
            img.thumbnail(
                (screen_width - 40, screen_height - 80), Image.Resampling.LANCZOS
            )
            img = img.convert("RGBA")

            photo = ctk.CTkImage(light_image=img, size=(img.width, img.height))
            label = ctk.CTkLabel(top, image=photo, text="")
            label.image = photo
            label.pack(padx=20, pady=20, expand=True)

        except Exception as e:
            print(f"[Error] Failed to display image: {e}")

    def __on_mousewheel(self, event):
        # Windows/macOS
        self.canvas.yview_scroll(-1 * int(event.delta / 120), "units")

    def __on_mousewheel_linux(self, event):
        # Linux専用（Button-4：上, Button-5：下）
        direction = -1 if event.num == 4 else 1
        self.canvas.yview_scroll(direction, "units")


# === 実行 ===
if __name__ == "__main__":
    initialize_database()
    app = App()
    app.mainloop()
