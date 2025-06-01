import hashlib
from functools import lru_cache
from pathlib import Path

import customtkinter as ctk
from config import (
    ENABLE_IMAGE_CACHE,
    IMAGE_DIR,
    SUPPORTED_FORMATS,
    THUMB_DIR,
    THUMBNAIL_SIZE,
)
from PIL import Image, ImageEnhance, ImageFilter


@lru_cache(maxsize=512)
def _cached_loader(
    image_path: str, size: tuple, shadow_offset: int
) -> tuple[ctk.CTkImage, ctk.CTkImage]:
    """
    サムネイル画像とホバー画像をキャッシュして返す。

    Args:
        image_path (str): 画像ファイルのパス
        size (tuple[int, int]): サムネイルサイズ
        shadow_offset (int): 影のずれピクセル

    Returns:
        tuple[CTkImage, CTkImage]: 通常画像とホバー用画像
    """
    return _generate_thumbnail_images(image_path, size, shadow_offset)


def load_thumbnail_image(
    image_path: str, size: tuple, shadow_offset: int
) -> tuple[ctk.CTkImage, ctk.CTkImage]:
    if ENABLE_IMAGE_CACHE:
        return _cached_loader(image_path, size, shadow_offset)
    else:
        _cached_loader.cache_clear()
        return _generate_thumbnail_images(image_path, size, shadow_offset)


def _hash_path(path: Path) -> str:
    return hashlib.md5(path.as_posix().encode("utf-8")).hexdigest()


def resize_images(registered: set[str]) -> list[tuple[str, str]]:
    images: list[tuple[str, str]] = []
    THUMB_DIR.mkdir(exist_ok=True)
    for img_path in IMAGE_DIR.rglob("*"):
        if (
            img_path.suffix.lower() not in SUPPORTED_FORMATS
            or str(img_path) in registered
        ):
            continue
        thumb_hash = _hash_path(img_path)
        thumb_path = THUMB_DIR / f"{thumb_hash}_thumb.png"

        img = Image.open(img_path)
        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        img.save(thumb_path)
        images.append((str(img_path), str(thumb_path)))
    return images


def _generate_thumbnail_images(
    image_path, size, shadow_offset=4
) -> tuple[ctk.CTkImage, ctk.CTkImage]:
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


def delete_image_files(image_path: str | Path, thumbnail_path: str | Path) -> None:
    """画像とサムネイルのファイルを削除する（存在確認付き）"""
    for path in [image_path, thumbnail_path]:
        try:
            p = Path(path)
            if p.exists():
                p.unlink()
        except Exception as e:
            print(f"[Error] ファイル削除失敗: {path} -> {e}")
