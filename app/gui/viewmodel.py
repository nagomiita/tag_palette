class GalleryViewModel:
    def __init__(self):
        self._show_favorites_only = False
        self._entries = []

    @property
    def show_favorites_only(self):
        return self._show_favorites_only

    def toggle_favorites(self):
        self._show_favorites_only = not self._show_favorites_only

    def get_entries(self):
        from db.query import (
            get_all_image_entries,
            get_favorite_image_entries,
        )

        self._entries = (
            get_favorite_image_entries()
            if self._show_favorites_only
            else get_all_image_entries()
        )
        return self._entries

    def get_image_by_id(self, image_id):
        from db.query import get_image_entry_by_id

        return get_image_entry_by_id(image_id)
