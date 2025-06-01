import customtkinter as ctk
from db.query import delete_image_entry, get_favorite_flag, toggle_favorite_flag


def _create_icon_button(
    parent: ctk.CTkBaseClass,
    text: str,
    fg_color: str,
    hover_color: str,
    command: callable,
) -> ctk.CTkButton:
    return ctk.CTkButton(
        parent,
        text=text,
        fg_color=fg_color,
        hover_color=hover_color,
        text_color="white",
        width=30,
        height=30,
        font=("Arial", 24),
        command=command,
    )


def create_delete_button(
    parent: ctk.CTkBaseClass, image_id: int, refresh_callback=None
) -> ctk.CTkButton:
    def on_delete():
        result = delete_image_entry(image_id)
        if result and refresh_callback:
            refresh_callback()

    return _create_icon_button(
        parent,
        text="🗑",
        fg_color="#cc4444",
        hover_color="#aa2222",
        command=on_delete,
    )


def create_favorite_button(
    parent: ctk.CTkBaseClass, image_id: int, update_callback=None
) -> ctk.CTkButton:
    is_fav = get_favorite_flag(image_id)

    def toggle():
        new_state = toggle_favorite_flag(image_id)
        if new_state is not None:
            btn.configure(
                text="♥" if new_state else "♡",
                fg_color="#ff9eb5" if new_state else "#1f6aa5",
            )
            if update_callback:
                update_callback(new_state)

    btn = _create_icon_button(
        parent,
        text="♥" if is_fav else "♡",
        fg_color="#ff9eb5" if is_fav else "#1f6aa5",
        hover_color="#c268a7" if is_fav else "#124c86",
        command=toggle,
    )
    return btn
