"""共通の環境変数読み込み。

.env ファイルから EAGLE_IMAGE_DIR / SQLITE_DB_PATH を読み込み、
argparse のデフォルト値として提供する。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def get_image_dir() -> Path | None:
    val = os.environ.get("EAGLE_IMAGE_DIR")
    return Path(val) if val else None


def get_db_path() -> Path | None:
    val = os.environ.get("SQLITE_DB_PATH")
    return Path(val) if val else None


def get_api_url() -> str:
    """Eagle API の URL を返す (env: EAGLE_API_URL)。"""
    return os.environ.get("EAGLE_API_URL", "http://localhost:8000")
