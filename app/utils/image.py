import hashlib
from datetime import datetime
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
from db.query import (
    add_image_entries,
    add_tag_entry,
    delete_image_entry,
    get_image_entry_by_id,
    get_registered_image_paths,
    update_image_embedding,
)
from PIL import Image, ImageEnhance, ImageFile, ImageFilter
from send2trash import send2trash
from tqdm import tqdm
from utils.folder import image_link_manager
from utils.logger import setup_logging
from utils.tagger import TagResult, generate_tags

from .embedding import tag_result_to_embedding

logger = setup_logging()

ImageFile.LOAD_TRUNCATED_IMAGES = True


class ImageProcessor:
    """画像処理の基本機能を提供するクラス"""

    def __init__(self, thumbnail_size: tuple[int, int] = THUMBNAIL_SIZE):
        self.thumbnail_size = thumbnail_size

    @staticmethod
    def resize_image(
        img_path: Path, size: tuple[int, int], channel: str = "RGBA"
    ) -> Image.Image:
        """画像を指定サイズにリサイズしたPIL Imageを返す"""
        try:
            with Image.open(img_path) as img:
                img = img.convert(channel)
                img.thumbnail(size, Image.Resampling.LANCZOS)
                return img
        except FileNotFoundError:
            logger.error(f"⚠ 失敗:画像の読み込みに失敗しました: {img_path}")
            raise

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
        """指定された画像を読み込み、最大横幅を制限してラベルとして返す"""
        screen_w = parent.winfo_screenwidth()
        screen_h = parent.winfo_screenheight()

        # 最大サイズを決定（最大横幅を制限）
        actual_max_width = (screen_w - 40) * 0.8
        actual_max_height = screen_h - 80
        img = self.resize_image(image_path, (actual_max_width, actual_max_height))
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

    @staticmethod
    def hash_path(path: Path) -> str:
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
        print("未登録の画像を探索中...")
        for img_path in self.image_dir.rglob("*"):
            if img_path.is_symlink():  # シンボリックリンク先のシンボリックは無視
                for child_path in img_path.rglob("*"):
                    if self._is_valid_image(child_path, registered):
                        unregistered.append(child_path)
            elif self._is_valid_image(img_path, registered):
                unregistered.append(img_path)
        print(f"未登録の画像数: {len(unregistered)}")
        return unregistered

    def _save_thumbnail(self, img: Image.Image, img_path: Path) -> Path:
        """PIL Imageをサムネイルパスに保存"""
        self.thumb_dir.mkdir(exist_ok=True)
        thumb_hash = self.hash_path(img_path)
        thumb_path = self.thumb_dir / f"{thumb_hash}_thumbnail.png"
        img.save(thumb_path)
        return thumb_path

    @staticmethod
    def extract_created_at(img_path: Path) -> datetime:
        """ファイルの作成日時を抽出してISO形式で返す"""
        ts = img_path.stat().st_birthtime
        return datetime.fromtimestamp(ts)

    def generate_thumbnails(
        self, image_paths: list[Path], processor: ImageProcessor
    ) -> list[tuple[Path, Path, datetime]]:
        """画像をサムネイルとして並列リサイズ＆保存"""
        args = [
            (path, processor.thumbnail_size, self.thumb_dir) for path in image_paths
        ]
        with Pool(processes=cpu_count()) as pool:
            results = list(pool.imap(_process_and_save, args))
        return [r for r in results if r is not None]

    def delete_image_files(self, image_path: Path, thumbnail_path: Path) -> None:
        """画像とサムネイルのファイルを削除"""
        for path in [image_path, thumbnail_path]:
            try:
                if path.exists():
                    send2trash(str(path))
            except Exception as e:
                logger.error(f"[Error] ファイル削除失敗: {path} -> {e}")


def _process_and_save(args) -> tuple[Path, Path, datetime]:
    """画像をリサイズしてサムネイルを保存するマルチプロセス対象の関数"""
    img_path, thumbnail_size, thumb_dir = args
    try:
        img = ImageProcessor.resize_image(img_path, thumbnail_size)  # リサイズ処理
        thumb_hash = ImageFileManager.hash_path(img_path)
        thumb_path = thumb_dir / f"{thumb_hash}_thumbnail.png"
        thumb_dir.mkdir(exist_ok=True)
        img.save(thumb_path)
        created_at = ImageFileManager.extract_created_at(img_path)
        return (img_path, thumb_path, created_at)
    except Exception as e:
        logger.error(f"⚠ 失敗: {img_path} → {e}")
        raise


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

    def generate_thumbnails(
        self, image_paths: list[Path]
    ) -> list[tuple[Path, Path, datetime]]:
        """サムネイル生成"""
        return self.file_manager.generate_thumbnails(image_paths, self.processor)

    def extract_created_at(self, img_path: Path) -> datetime:
        """画像のキャプチャ日時を抽出"""
        return self.file_manager.extract_created_at(img_path)

    def delete_image_files(self, image_id: int) -> bool:
        """画像ファイル削除"""
        image_entry = get_image_entry_by_id(image_id)
        if delete_image_entry(image_id):
            logger.info(f"✅ 画像ID {image_id} のエントリを削除しました。")
            self.file_manager.delete_image_files(
                Path(image_entry.image_path), Path(image_entry.thumbnail_path)
            )
            return True
        return False

    def clear_cache(self):
        """キャッシュクリア"""
        self.cache.clear_cache()

    def register_new_images(self, is_first_run: bool = True):
        print("登録済みイラスト探索開始")
        registered = get_registered_image_paths()
        print("登録済みイラスト取得完了")
        if not registered or not is_first_run:
            logger.info("画像フォルダを選択してください。")
            selected_folder = image_link_manager.select_image_folder()
            if selected_folder:
                image_link_manager.create_symlink(selected_folder)
        print("未登録イラスト探索開始")
        unregistered = image_manager.find_unregistered_images(registered)
        if not unregistered:
            logger.info("✅ 新しい画像はありません。")
            return
        logger.info("🖼 サムネイル画像の生成中...")
        images = image_manager.generate_thumbnails(tqdm(unregistered))

        logger.info(f"📥 {len(images)} 件の画像をDBに登録中...")
        results = add_image_entries(tqdm(images))
        all_tag_results: list[dict[str, list[TagResult]]] = []
        for item in tqdm(results, desc="generating tags"):
            image_id = item[0]
            tag_result = {}
            tag_result[image_id] = generate_tags(image_path=item[1])
            all_tag_results.append(tag_result)

        logger.info("🖼 DBにタグを登録中...")
        for tag_results in tqdm(all_tag_results):
            for image_id, tag_result in tag_results.items():
                for result in tag_result:
                    add_tag_entry(image_id, result.model_name, result.tags)
                    embedding = tag_result_to_embedding(result.tags)
                    update_image_embedding(image_id, embedding)
        logger.info("✅ 新しい画像を登録しました。")

    def truncate_filename(self, filename: str, max_length: int = 18) -> str:
        """ファイル名を指定された長さに制限する

        Args:
            filename: 元のファイル名
            max_length: 最大文字数（デフォルト: 18）

        Returns:
            制限された文字数のファイル名
        """
        if len(filename) <= max_length:
            return filename

        # 拡張子を保持しながら制限
        path_obj = Path(filename)
        stem = path_obj.stem
        suffix = path_obj.suffix
        max_stem_length = max_length - len(suffix)

        if max_stem_length > 0:
            return stem[:max_stem_length] + suffix
        else:
            # 拡張子が長すぎる場合は全体を制限
            return filename[:max_length]


image_manager = ImageManager()
