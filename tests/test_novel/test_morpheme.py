"""Tests for morpheme analysis."""

from tag_palette.novel.morpheme import extract_morphemes


def test_extract_nouns():
    """名詞が抽出されること。"""
    result = extract_morphemes("東京タワーは観光名所です。")
    surfaces = {s for (s, p) in result if p == "名詞"}
    assert "東京" in surfaces or "タワー" in surfaces or "観光" in surfaces


def test_extract_verbs():
    """動詞が抽出されること。"""
    result = extract_morphemes("猫が走る。")
    surfaces = {s for (s, p) in result if p == "動詞"}
    assert "走る" in surfaces or "走" in surfaces


def test_extract_adjectives():
    """形容詞が抽出されること。"""
    result = extract_morphemes("空が美しい。")
    surfaces = {s for (s, p) in result if p == "形容詞"}
    assert "美しい" in surfaces or "美しく" in surfaces or len(surfaces) > 0


def test_exclude_particles():
    """助詞・助動詞が除外されること。"""
    result = extract_morphemes("猫が走る。")
    pos_set = {p for (_, p) in result}
    assert "助詞" not in pos_set
    assert "助動詞" not in pos_set


def test_count():
    """同じ形態素の出現回数がカウントされること。"""
    result = extract_morphemes("猫と猫と猫。")
    cat_count = result.get(("猫", "名詞"), 0)
    assert cat_count >= 2
