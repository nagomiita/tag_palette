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
from tqdm import tqdm


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


def find_unregistered_images(registered: set[str]) -> list[Path]:
    """登録されていない画像のパスを探索（シンボリックリンク先の画像も含むが循環参照は除外）"""

    def _is_valid_image(img_path: Path, registered: set[str]) -> bool:
        """画像がサポート形式で、未登録かどうかを判定"""
        return (
            img_path.suffix.lower() in SUPPORTED_FORMATS
            and "_thumbnail" not in img_path.stem
            and str(img_path) not in registered
        )

    unregistered = []
    for img_path in IMAGE_DIR.rglob("*"):
        if img_path.is_symlink():
            for child_path in img_path.rglob("*"):
                if _is_valid_image(child_path, registered):
                    unregistered.append(child_path)
        elif _is_valid_image(img_path, registered):
            unregistered.append(img_path)
    return unregistered


def generate_thumbnails(image_paths: list[Path]) -> list[tuple[str, str]]:
    """画像をサムネイルとしてリサイズし保存"""
    thumbnails = []
    for img_path in tqdm(image_paths):
        img = _resize_image(img_path, THUMBNAIL_SIZE)
        thumb_path = _save_thumbnail_image(img, img_path)
        thumbnails.append((str(img_path), str(thumb_path)))
    return thumbnails


def _resize_image(img_path: Path, size: tuple[int, int]) -> Image.Image:
    """画像を指定サイズにリサイズしたPIL Imageを返す"""
    img = Image.open(img_path)
    img.thumbnail(size, Image.Resampling.LANCZOS)
    return img


def _save_thumbnail_image(img: Image.Image, img_path: Path) -> Path:
    """PIL Imageをサムネイルパスに保存する"""
    THUMB_DIR.mkdir(exist_ok=True)
    thumb_hash = _hash_path(img_path)
    thumb_path = THUMB_DIR / f"{thumb_hash}_thumbnail.png"
    img.save(thumb_path)
    return thumb_path


def _generate_thumbnail_images(
    image_path: Path, size, shadow_offset=4
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
    img = _resize_image(image_path, size)
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
    max_width = screen_w - (screen_w / 3)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize(
            (int(img.width * ratio), int(img.height * ratio)), Image.Resampling.LANCZOS
        )

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
