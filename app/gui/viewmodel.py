from db.models import ImageEntry
from db.query import (
    delete_image_entry,
    get_all_image_entries,
    get_favorite_flag,
    get_favorite_image_entries,
    get_image_entry_by_id,
    toggle_favorite_flag,
)


class GalleryViewModel:
    def __init__(self):
        self._show_favorites_only = False
        self._entries: list[ImageEntry] = []

    @property
    def show_favorites_only(self):
        return self._show_favorites_only

    def toggle_favorites(self):
        self._show_favorites_only = not self._show_favorites_only

    def get_entries(self):
        self._entries = (
            get_favorite_image_entries()
            if self._show_favorites_only
            else get_all_image_entries()
        )
        return self._entries

    def get_image_by_id(self, image_id):
        return get_image_entry_by_id(image_id)

    def get_favorite_state(self, image_id) -> bool:
        return get_favorite_flag(image_id)

    def toggle_favorite(self, image_id) -> bool:
        return toggle_favorite_flag(image_id)

    def delete_image(self, image_id) -> bool:
        return delete_image_entry(image_id)


class ImageThumbnailViewModel:
    def __init__(self, image_id: int, image_path: str):
        self.image_id = image_id
        self.image_path = image_path

    def get_favorite_state(self) -> bool:
        return get_favorite_flag(self.image_id)

    def toggle_favorite(self) -> bool:
        return toggle_favorite_flag(self.image_id)

    def delete_image(self) -> bool:
        return delete_image_entry(self.image_id)
