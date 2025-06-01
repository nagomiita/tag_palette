from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageEnhance, ImageFilter


def generate_thumbnail_images(image_path, size, shadow_offset=4):
    """
    サムネイル画像とホバー用画像を生成するユーティリティ関数。

    Args:
        image_path (Path): 画像ファイルのパス
        size (tuple): サムネイルサイズ (width, height)
        shadow_offset (int): 影のずれピクセル数

    Returns:
        tuple: (通常表示用CTkImage, ホバー用CTkImage)
    """
    img = Image.open(image_path)
    img.thumbnail(size, Image.Resampling.LANCZOS)
    img = img.convert("RGBA")

    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    x = (size[0] - img.width) // 2
    y = (size[1] - img.height) // 2
    canvas.paste(img, (x, y), img)

    shadow = canvas.copy().filter(ImageFilter.GaussianBlur(2))
    final_img = Image.new(
        "RGBA",
        (size[0] + shadow_offset, size[1] + shadow_offset),
        (0, 0, 0, 0),
    )
    final_img.paste(shadow, (2, 2), shadow)
    final_img.paste(canvas, (0, 0), canvas)

    hover_img = ImageEnhance.Brightness(canvas).enhance(0.6)

    return (
        ctk.CTkImage(light_image=final_img, size=size),
        ctk.CTkImage(light_image=hover_img, size=size),
    )


def load_full_image(parent: ctk.CTkBaseClass, image_path: str | Path) -> ctk.CTkLabel:
    """
    指定された画像を読み込み、ウィンドウに収まるように縮小してラベルとして返す。
    """
    img = Image.open(image_path)
    screen_w = parent.winfo_screenwidth()
    screen_h = parent.winfo_screenheight()
    img.thumbnail((screen_w - 40, screen_h - 80), Image.Resampling.LANCZOS)
    img = img.convert("RGBA")

    photo = ctk.CTkImage(light_image=img, size=(img.width, img.height))
    label = ctk.CTkLabel(parent, image=photo, text="")
    label.image = photo  # ガーベジコレクション防止
    return label
