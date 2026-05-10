from tag_palette.media.categorize import CATEGORY_ID_TO_NAME, get_tag_category


def test_category_id_to_name_mapping():
    assert CATEGORY_ID_TO_NAME[0] == "general"
    assert CATEGORY_ID_TO_NAME[1] == "artist"
    assert CATEGORY_ID_TO_NAME[3] == "copyright"
    assert CATEGORY_ID_TO_NAME[4] == "character"
    assert CATEGORY_ID_TO_NAME[5] == "meta"


def test_category_id_to_name_completeness():
    assert len(CATEGORY_ID_TO_NAME) == 5


def test_get_tag_category_known_tag():
    assert get_tag_category("1girl") == "general"
