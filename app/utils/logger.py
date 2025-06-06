import logging
import sys
from logging import FileHandler, StreamHandler


def setup_logging():
    """Setup logging configuration"""
    # ロガー取得
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    # 重複ハンドラ追加防止
    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler = FileHandler("main.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        stream_handler = StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)

    return logger
