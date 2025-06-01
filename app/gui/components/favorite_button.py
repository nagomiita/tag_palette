import customtkinter as ctk
from db.query import get_favorite_flag, toggle_favorite_flag


def create_favorite_button(
    parent: ctk.CTkBaseClass, image_id: int, update_callback=None
) -> ctk.CTkButton:
    """
    お気に入りトグル用のボタンを生成し、親ウィジェットに配置する。
    :param parent: ボタンの親ウィジェット
    :param image_id: 対象の画像ID
    :param update_callback: 状態変更時に呼び出される追加処理（任意）
    :return: CTkButton インスタンス
    """
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

    btn = ctk.CTkButton(
        parent,
        text="♥" if is_fav else "♡",
        fg_color="#ff9eb5" if is_fav else "#1f6aa5",
        width=30,
        height=30,
        font=("Arial", 24),
        command=toggle,
    )
    return btn
