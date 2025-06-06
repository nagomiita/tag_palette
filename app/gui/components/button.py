import customtkinter as ctk
from customtkinter import CTkFont


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
        width=20,
        height=20,
        font=("Arial", 20),
        command=command,
    )


def create_delete_button(parent: ctk.CTkBaseClass, command: callable) -> ctk.CTkButton:
    return _create_icon_button(
        parent,
        text="🗑",
        fg_color="#cc4444",
        hover_color="#aa2222",
        command=command,
    )


def create_favorite_button(
    parent: ctk.CTkBaseClass, is_favorite: bool, command: callable
) -> ctk.CTkButton:
    return _create_icon_button(
        parent,
        text="♥" if is_favorite else "♡",
        fg_color="#ff9eb5" if is_favorite else "#1f6aa5",
        hover_color="#c268a7" if is_favorite else "#124c86",
        command=command,
    )


def create_button(
    parent: ctk.CTkBaseClass,
    text: str,
    command: callable,
    fg_color: str = "#1f6aa5",
) -> ctk.CTkButton:
    return ctk.CTkButton(
        parent,
        text=text,
        text_color="white",
        font=CTkFont(weight="bold"),
        command=command,
        fg_color=fg_color,
    )
