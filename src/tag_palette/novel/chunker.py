"""Chunk splitting for novel text.

Step 1: Split by kind (dialogue / thought / narrative)
Step 2: Split long narrative chunks (500-1000 chars)
Step 3: Assign seq numbers
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Regex to find dialogue 「...」/『...』 and thought (...) or （...）
_BRACKET_PATTERN = re.compile(
    r"(「[^」]*」|『[^』]*』)"   # dialogue
    r"|((?:\([^)]*\)|（[^）]*）))"  # thought
)

MIN_CHUNK_SIZE = 500
MAX_CHUNK_SIZE = 1000

# Separators for splitting narrative text
_SEPARATOR_PATTERN = re.compile(r"(?<=[。！？\n])")


@dataclass
class Chunk:
    seq: int
    kind: str  # "dialogue" | "thought" | "narrative"
    body: str


def _split_narrative(text: str) -> list[str]:
    """Split a long narrative text into chunks of 500-1000 chars.

    Split at separators (。！？\\n) after reaching 500 chars.
    """
    if len(text) <= MIN_CHUNK_SIZE:
        return [text] if text.strip() else []

    separators = set("。！？\n")
    result = []
    start = 0

    for i, ch in enumerate(text):
        chunk_len = i - start + 1
        if chunk_len >= MIN_CHUNK_SIZE and ch in separators:
            result.append(text[start : i + 1])
            start = i + 1

    # Remaining text: keep as separate chunk
    if start < len(text):
        remaining = text[start:]
        if remaining.strip():
            result.append(remaining)

    return result


def split_by_kind(text: str) -> list[tuple[str, str]]:
    """Split text into (kind, body) pairs preserving order.

    Returns list of ("dialogue"|"thought"|"narrative", text) tuples.
    """
    segments: list[tuple[str, str]] = []
    last_end = 0

    for m in _BRACKET_PATTERN.finditer(text):
        # Narrative before this match
        before = text[last_end:m.start()]
        if before.strip():
            segments.append(("narrative", before))

        if m.group(1):  # 「...」
            segments.append(("dialogue", m.group(1)))
        elif m.group(2):  # (...) or （...）
            segments.append(("thought", m.group(2)))

        last_end = m.end()

    # Remaining narrative after last match
    remaining = text[last_end:]
    if remaining.strip():
        segments.append(("narrative", remaining))

    return segments


def chunk_text(text: str) -> list[Chunk]:
    """Full chunking pipeline: split by kind, then split long narratives."""
    segments = split_by_kind(text)

    chunks: list[Chunk] = []
    seq = 0

    for kind, body in segments:
        if kind == "narrative":
            for sub in _split_narrative(body):
                chunks.append(Chunk(seq=seq, kind="narrative", body=sub))
                seq += 1
        else:
            chunks.append(Chunk(seq=seq, kind=kind, body=body))
            seq += 1

    return chunks
