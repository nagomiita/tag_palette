from tag_palette import detect_sensitive, get_tag_category


def test_public_api_smoke_imports():
    assert callable(detect_sensitive)
    assert get_tag_category("1girl") == "general"


def test_detect_sensitive_export_works():
    result = detect_sensitive(
        ratings={
            "general": 0.1,
            "sensitive": 0.2,
            "questionable": 0.4,
            "explicit": 0.3,
        }
    )
    assert result["is_sensitive"] is True
    assert result["method"] == "wd14_rating"
