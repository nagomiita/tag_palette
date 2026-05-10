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


def get_ollama_hosts() -> list[str]:
    """Ollama ホスト一覧を返す (env: OLLAMA_HOSTS, カンマ区切り)。

    OLLAMA_HOSTS が未設定の場合は旧 OLLAMA_HOST にフォールバックし、
    それも未設定なら localhost をデフォルトとする。
    """
    val = os.environ.get("OLLAMA_HOSTS")
    if val:
        return [h.strip() for h in val.split(",") if h.strip()]
    # 旧設定との後方互換
    single = os.environ.get("OLLAMA_HOST")
    if single:
        return [single.strip()]
    return ["http://localhost:11434"]
