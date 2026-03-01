from tag_palette.tagger import TagResult


def test_tag_result_creation():
    result = TagResult(model_name="test-model", tags={"1girl": 0.95, "blue_eyes": 0.8})
    assert result.model_name == "test-model"
    assert result.tags["1girl"] == 0.95
    assert result.tags["blue_eyes"] == 0.8


def test_tag_result_empty_tags():
    result = TagResult(model_name="test-model", tags={})
    assert result.model_name == "test-model"
    assert len(result.tags) == 0
