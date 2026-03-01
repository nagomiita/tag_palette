from tag_palette.translations import is_japanese, is_preferably_japanese


def test_is_japanese_with_kanji():
    assert is_japanese("初音ミク") is True


def test_is_japanese_with_hiragana():
    assert is_japanese("おはよう") is True


def test_is_japanese_with_katakana():
    assert is_japanese("カタカナ") is True


def test_is_japanese_with_ascii():
    assert is_japanese("hello") is False


def test_is_japanese_mixed():
    assert is_japanese("hello世界") is True


def test_is_preferably_japanese_with_kana():
    assert is_preferably_japanese("ミク") is True
    assert is_preferably_japanese("みく") is True


def test_is_preferably_japanese_kanji_only():
    assert is_preferably_japanese("初音") is False


def test_is_preferably_japanese_ascii():
    assert is_preferably_japanese("hello") is False
