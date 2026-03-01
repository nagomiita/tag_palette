from tag_palette.sensitive import SENSITIVE_KEYWORDS, is_sensitive


def test_is_sensitive_true():
    assert is_sensitive("bondage") is True
    assert is_sensitive("nipples") is True


def test_is_sensitive_false():
    assert is_sensitive("flower") is False
    assert is_sensitive("1girl") is False
    assert is_sensitive("blue_eyes") is False


def test_is_sensitive_case_insensitive():
    assert is_sensitive("BONDAGE") is True
    assert is_sensitive("Bondage") is True


def test_sensitive_keywords_is_frozenset():
    assert isinstance(SENSITIVE_KEYWORDS, frozenset)


def test_sensitive_keywords_not_empty():
    assert len(SENSITIVE_KEYWORDS) > 0
