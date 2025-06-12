import os
from pathlib import Path

# 環境変数 APP_ENV=dev のときは開発モード
ENV = os.environ.get("APP_ENV", "prod")  # デフォルトは "prod"
IS_DEV = ENV == "dev"

FONT_TYPE = "meiryo"
FONT_SIZE = 13
THUMBNAIL_SIZE = (190, 190)

IMAGE_DIR = Path("images_dev") if IS_DEV else Path("images")
THUMB_DIR = Path("thumbnails_dev") if IS_DEV else Path("thumbnails")
DB_PATH = "images_dev.db" if IS_DEV else "images.db"

SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}
MARGIN = 10
SHADOW_OFFSET = 4
ENABLE_IMAGE_CACHE = True
