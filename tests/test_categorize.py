from tag_palette.media.categorize import CATEGORY_ID_TO_NAME


def test_category_id_to_name_mapping():
    assert CATEGORY_ID_TO_NAME[0] == "general"
    assert CATEGORY_ID_TO_NAME[1] == "artist"
    assert CATEGORY_ID_TO_NAME[3] == "copyright"
    assert CATEGORY_ID_TO_NAME[4] == "character"
    assert CATEGORY_ID_TO_NAME[5] == "meta"


def test_category_id_to_name_completeness():
    assert len(CATEGORY_ID_TO_NAME) == 5
