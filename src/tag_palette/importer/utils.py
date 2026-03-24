"""共通ユーティリティ関数。"""

from __future__ import annotations

from datetime import datetime
from itertools import islice

BATCH_SIZE = 500


def _now_iso() -> str:
    return datetime.now().isoformat()


def _chunked(iterable, size: int):
    it = iter(iterable)
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            break
        yield chunk
