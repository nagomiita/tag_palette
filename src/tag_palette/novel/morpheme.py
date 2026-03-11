"""Morpheme analysis using MeCab (fugashi + unidic-lite)."""

from __future__ import annotations

import re
from collections import Counter

import fugashi

_TARGET_POS = {"名詞", "動詞", "形容詞"}

# ひらがなのみで構成された1文字の形態素を除外
_HIRAGANA_1CHAR = re.compile(r"^[\u3040-\u309F]$")

# 汎用的すぎてタグ候補として意味が薄い語
_STOP_WORDS = {
    # 汎用動詞
    "する", "いる", "ある", "なる", "できる", "くる", "いく", "おる",
    "くれる", "もらう", "あげる", "やる", "つく", "なす", "おく",
    "みる", "しまう", "しれる", "れる", "られる", "せる", "させる",
    # 汎用形容詞
    "ない", "よい", "いい",
    # 汎用名詞（形式名詞・代名詞等）
    "こと", "もの", "ところ", "とき", "ため", "ほう", "よう",
    "それ", "これ", "あれ", "どれ",
    "の", "ん",
}

_tagger: fugashi.Tagger | None = None


def _get_tagger() -> fugashi.Tagger:
    global _tagger
    if _tagger is None:
        _tagger = fugashi.Tagger()
    return _tagger


def _is_stopword(surface: str) -> bool:
    """Check if a surface form should be excluded."""
    if surface in _STOP_WORDS:
        return True
    if _HIRAGANA_1CHAR.match(surface):
        return True
    return False


def extract_morphemes(text: str) -> dict[tuple[str, str], int]:
    """Extract morphemes from text and return {(surface, pos): count}.

    Only extracts nouns, verbs, and adjectives.
    Excludes stopwords and single hiragana characters.
    """
    tagger = _get_tagger()
    counts: Counter[tuple[str, str]] = Counter()

    for word in tagger(text):
        if word.feature.pos1 in _TARGET_POS:
            surface = word.surface
            if _is_stopword(surface):
                continue
            pos = word.feature.pos1
            counts[(surface, pos)] += 1

    return dict(counts)
