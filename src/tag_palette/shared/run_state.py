"""前回実行時刻の管理とログ設定。"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

STATE_FILE = Path("last_run.txt")


def setup_logging(log_file: Path | None = None) -> None:
    """ログ設定。ファイル指定時はファイルにも出力。"""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


def _state_path(image_dir: Path) -> Path:
    """image_dir の親ディレクトリ (eagle.library/) に .last_run ファイルを配置。"""
    return image_dir.parent / STATE_FILE


def load_last_run(image_dir: Path) -> datetime | None:
    """前回実行時刻を読み込む。初回は None。"""
    path = _state_path(image_dir)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return datetime.fromisoformat(text)
    except (ValueError, OSError):
        return None


def save_last_run(image_dir: Path, run_time: datetime) -> None:
    """実行時刻を状態ファイルに書き込む。"""
    path = _state_path(image_dir)
    path.write_text(run_time.isoformat(), encoding="utf-8")
