from tag_palette.media.sensitive import is_sensitive_by_ratings, detect_sensitive


def test_is_sensitive_by_ratings_nsfw():
    ratings = {"general": 0.1, "sensitive": 0.2, "questionable": 0.4, "explicit": 0.3}
    assert is_sensitive_by_ratings(ratings) is True


def test_is_sensitive_by_ratings_safe():
    ratings = {"general": 0.8, "sensitive": 0.15, "questionable": 0.03, "explicit": 0.02}
    assert is_sensitive_by_ratings(ratings) is False


def test_is_sensitive_by_ratings_none():
    assert is_sensitive_by_ratings(None) is None
    assert is_sensitive_by_ratings({}) is None


def test_detect_sensitive_with_wd14():
    ratings = {"general": 0.1, "sensitive": 0.2, "questionable": 0.4, "explicit": 0.3}
    result = detect_sensitive(ratings=ratings)
    assert result["is_sensitive"] is True
    assert result["method"] == "wd14_rating"


def test_detect_sensitive_no_input():
    result = detect_sensitive()
    assert result["is_sensitive"] is False
    assert result["method"] == "none"
