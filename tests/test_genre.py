import re


def test_genre_regex_extraction():
    """get_genres の内部で使われる正規表現パターンのテスト。"""
    tag_name = "artoria_pendragon_(fate)"
    matches = re.findall(r"\((.*?)\)", tag_name)
    assert matches == ["fate"]


def test_genre_regex_multiple():
    tag_name = "artoria_pendragon_(saber)_(fate)"
    matches = re.findall(r"\((.*?)\)", tag_name)
    assert matches == ["saber", "fate"]


def test_genre_regex_no_match():
    tag_name = "1girl"
    matches = re.findall(r"\((.*?)\)", tag_name)
    assert matches == []
