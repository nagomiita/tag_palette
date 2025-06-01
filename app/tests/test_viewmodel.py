import pytest
from gui.viewmodel import GalleryViewModel


@pytest.fixture
def sample_entries():
    return [
        {"id": 1, "image_path": "a.png"},
        {"id": 2, "image_path": "b.png"},
    ]


def test_toggle_favorites():
    vm = GalleryViewModel()
    assert vm.show_favorites_only is False
    vm.toggle_favorites()
    assert vm.show_favorites_only is True


def test_get_entries(monkeypatch, sample_entries):
    # get_all_image_entries をモック
    monkeypatch.setattr("db.query.get_all_image_entries", lambda: sample_entries)
    vm = GalleryViewModel()
    entries = vm.get_entries()
    assert entries == sample_entries


def test_get_favorite_entries(monkeypatch, sample_entries):
    # get_favorite_image_entries をモック
    monkeypatch.setattr("db.query.get_favorite_image_entries", lambda: sample_entries)
    vm = GalleryViewModel()
    vm.toggle_favorites()
    entries = vm.get_entries()
    assert vm.show_favorites_only is True
    assert entries == sample_entries


def test_get_image_by_id(monkeypatch):
    expected = {"id": 1, "image_path": "x.png"}
    monkeypatch.setattr(
        "db.query.get_image_entry_by_id", lambda id: expected if id == 1 else None
    )

    vm = GalleryViewModel()
    result = vm.get_image_by_id(1)
    assert result == expected

    result_none = vm.get_image_by_id(999)
    assert result_none is None
