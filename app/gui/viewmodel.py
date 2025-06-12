from db.models import ImageEntry
from db.query import (
    get_entries_by_tag,
    get_favorite_flag,
    get_filtered_image_entries,
    get_image_entry_by_id,
    get_tags_for_image,
    toggle_favorite_flag,
)
from utils.image import image_manager


class GalleryViewModel:
    def __init__(self):
        self._entries: list[ImageEntry] = []
        self._show_favorites_only: bool = False
        self._show_sensitive: bool = False

    @property
    def show_favorites_only(self):
        return self._show_favorites_only

    @property
    def show_sensitive(self):
        return self._show_sensitive

    def toggle_favorites(self):
        self._show_favorites_only = not self._show_favorites_only

    def toggle_sensitive(self):
        self._show_sensitive = not self._show_sensitive

    def get_entries(
        self, favorites_only: bool = False, include_sensitive: bool = False
    ):
        self._entries = get_filtered_image_entries(
            favorites_only=favorites_only, include_sensitive=include_sensitive
        )
        return self._entries

    def get_image_by_id(self, image_id) -> ImageEntry | None:
        return get_image_entry_by_id(image_id)

    def get_favorite_state(self, image_id) -> bool:
        return get_favorite_flag(image_id)

    def toggle_favorite(self, image_id) -> bool:
        return toggle_favorite_flag(image_id)

    def delete_image(self, image_id) -> bool:
        return image_manager.delete_image_files(image_id)

    def get_tags_for_image(self, image_id) -> list[str]:
        """Fetch tags associated with a specific image."""
        return get_tags_for_image(image_id)

    def get_entries_by_tag(
        self,
        tag_name: str,
        favorites_only: bool = False,
        include_sensitive: bool = True,
    ) -> list[ImageEntry]:
        """Fetch entries associated with a specific tag."""
        return get_entries_by_tag(tag_name, favorites_only, include_sensitive)


class ImageThumbnailViewModel:
    def __init__(self, image_id: int, image_path: str):
        self.image_id = image_id
        self.image_path = image_path

    def get_favorite_state(self) -> bool:
        return get_favorite_flag(self.image_id)

    def toggle_favorite(self) -> bool:
        return toggle_favorite_flag(self.image_id)

    def delete_image(self) -> bool:
        return image_manager.delete_image_files(self.image_id)
