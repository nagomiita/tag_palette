import hashlib
from functools import lru_cache
from multiprocessing import Pool, cpu_count
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


def _process_and_save(args):
    """画像をリサイズしてサムネイルを保存するマルチプロセス対象の関数"""
    img_path, thumbnail_size, thumb_dir = args
    try:
        with Image.open(img_path) as img:
            img = img.convert("RGB")
            img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)

            thumb_hash = hashlib.md5(img_path.as_posix().encode("utf-8")).hexdigest()
            thumb_path = thumb_dir / f"{thumb_hash}_thumbnail.png"
            thumb_dir.mkdir(exist_ok=True)
            img.save(thumb_path)

            return (str(img_path), str(thumb_path))
    except Exception as e:
        print(f"⚠ 失敗: {img_path} → {e}")
        return None


class ImageProcessor:
    """画像処理の基本機能を提供するクラス"""

    def __init__(self, thumbnail_size: tuple[int, int] = THUMBNAIL_SIZE):
        self.thumbnail_size = thumbnail_size

    def resize_image(
        self, img_path: Path, size: tuple[int, int], channel: str = "RGBA"
    ) -> Image.Image:
        """画像を指定サイズにリサイズしたPIL Imageを返す"""
        with Image.open(img_path) as img:
            img = img.convert(channel)
            img.thumbnail(size, Image.Resampling.LANCZOS)
            return img

    def create_thumbnail_with_shadow(
        self, image_path: Path, size: tuple[int, int], shadow_offset: int = 4
    ) -> tuple[ctk.CTkImage, ctk.CTkImage]:
        """サムネイル画像とホバー用画像を生成"""
        img = self.resize_image(image_path, size)
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

    def load_full_image(
        self, parent: ctk.CTkBaseClass, image_path: Path
    ) -> ctk.CTkLabel:
        """指定された画像を読み込み、ウィンドウに収まるように縮小してラベルとして返す"""
        screen_w = parent.winfo_screenwidth()
        screen_h = parent.winfo_screenheight()
        img = self.resize_image(image_path, (screen_w - 40, screen_h - 80))
        photo = ctk.CTkImage(light_image=img, size=(img.width, img.height))
        label = ctk.CTkLabel(parent, image=photo, text="")
        label.image = photo  # ガーベジコレクション防止
        return label


class ImageCache:
    """画像キャッシュを管理するクラス"""

    def __init__(self, enable_cache: bool = ENABLE_IMAGE_CACHE):
        self.enable_cache = enable_cache

    @lru_cache(maxsize=512)
    def _cached_loader(
        self,
        image_path: Path,
        size: tuple[int, int],
        shadow_offset: int,
        processor: ImageProcessor,
    ) -> tuple[ctk.CTkImage, ctk.CTkImage]:
        """キャッシュされたローダー"""
        return processor.create_thumbnail_with_shadow(image_path, size, shadow_offset)

    def get_thumbnail(
        self,
        image_path: Path,
        size: tuple[int, int],
        shadow_offset: int,
        processor: ImageProcessor,
    ) -> tuple[ctk.CTkImage, ctk.CTkImage]:
        """サムネイル画像を取得（キャッシュ有効時はキャッシュから）"""
        if self.enable_cache:
            return self._cached_loader(image_path, size, shadow_offset, processor)
        else:
            self._cached_loader.cache_clear()
            return processor.create_thumbnail_with_shadow(
                image_path, size, shadow_offset
            )

    def clear_cache(self):
        """キャッシュをクリア"""
        self._cached_loader.cache_clear()


class ImageFileManager:
    """画像ファイルの管理を行うクラス"""

    def __init__(self, image_dir: Path = IMAGE_DIR, thumb_dir: Path = THUMB_DIR):
        self.image_dir = image_dir
        self.thumb_dir = thumb_dir
        self.supported_formats = SUPPORTED_FORMATS

    def _hash_path(self, path: Path) -> str:
        """パスのハッシュを生成"""
        return hashlib.md5(path.as_posix().encode("utf-8")).hexdigest()

    def _is_valid_image(self, img_path: Path, registered: set[str]) -> bool:
        """画像がサポート形式で、未登録かどうかを判定"""
        return (
            img_path.suffix.lower()
            in self.supported_formats  # サポートされている形式か
            and "_thumbnail" not in img_path.stem  # サムネイルでないか
            and str(img_path) not in registered  # 登録されていないか
        )

    def find_unregistered_images(self, registered: set[str]) -> list[Path]:
        """登録されていない画像のパスを探索"""
        unregistered: list[Path] = []
        for img_path in self.image_dir.rglob("*"):
            if img_path.is_symlink():  # シンボリックリンク先のシンボリックは無視
                for child_path in img_path.rglob("*"):
                    if self._is_valid_image(child_path, registered):
                        unregistered.append(child_path)
            elif self._is_valid_image(img_path, registered):
                unregistered.append(img_path)
        return unregistered

    def _save_thumbnail(self, img: Image.Image, img_path: Path) -> Path:
        """PIL Imageをサムネイルパスに保存"""
        self.thumb_dir.mkdir(exist_ok=True)
        thumb_hash = self._hash_path(img_path)
        thumb_path = self.thumb_dir / f"{thumb_hash}_thumbnail.png"
        img.save(thumb_path)
        return thumb_path

    def generate_thumbnails(
        self, image_paths: list[Path], processor: ImageProcessor
    ) -> list[tuple[str, str]]:
        """画像をサムネイルとして並列リサイズ＆保存"""
        args = [
            (path, processor.thumbnail_size, self.thumb_dir) for path in image_paths
        ]
        with Pool(processes=cpu_count()) as pool:
            results = list(tqdm(pool.imap(_process_and_save, args), total=len(args)))
        return [r for r in results if r is not None]

    def delete_image_files(self, image_path: Path, thumbnail_path: Path) -> None:
        """画像とサムネイルのファイルを削除"""
        for path in [image_path, thumbnail_path]:
            try:
                if path.exists():
                    path.unlink()
            except Exception as e:
                print(f"[Error] ファイル削除失敗: {path} -> {e}")


class ImageManager:
    """画像管理の統合クラス"""

    def __init__(
        self,
        image_dir: Path = IMAGE_DIR,
        thumb_dir: Path = THUMB_DIR,
        thumbnail_size: tuple[int, int] = THUMBNAIL_SIZE,
        enable_cache: bool = ENABLE_IMAGE_CACHE,
    ):
        self.processor = ImageProcessor(thumbnail_size)
        self.cache = ImageCache(enable_cache=enable_cache)
        self.file_manager = ImageFileManager(image_dir, thumb_dir)

    def load_thumbnail_image(
        self, image_path: Path, size: tuple[int, int], shadow_offset: int = 4
    ) -> tuple[ctk.CTkImage, ctk.CTkImage]:
        """サムネイル画像を読み込み"""
        return self.cache.get_thumbnail(image_path, size, shadow_offset, self.processor)

    def load_full_image(
        self, parent: ctk.CTkBaseClass, image_path: Path
    ) -> ctk.CTkLabel:
        """フルサイズ画像を読み込み"""
        return self.processor.load_full_image(parent, image_path)

    def find_unregistered_images(self, registered: set[str]) -> list[Path]:
        """未登録画像を検索"""
        return self.file_manager.find_unregistered_images(registered)

    def generate_thumbnails(self, image_paths: list[Path]) -> list[tuple[str, str]]:
        """サムネイル生成"""
        return self.file_manager.generate_thumbnails(image_paths, self.processor)

    def delete_image_files(self, image_path: Path, thumbnail_path: Path) -> None:
        """画像ファイル削除"""
        self.file_manager.delete_image_files(image_path, thumbnail_path)

    def clear_cache(self):
        """キャッシュクリア"""
        self.cache.clear_cache()


image_manager = ImageManager()
