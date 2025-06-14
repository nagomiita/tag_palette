from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk
from db.models import ImageEntry
from gui.base import BaseToplevel
from gui.components.button import create_delete_button, create_favorite_button
from utils.file_operations import FileOperationManager
from utils.image import image_manager


class Original(BaseToplevel):
    def __init__(
        self,
        parent: ctk.CTk | ctk.CTkToplevel,
        entry: ImageEntry,
        tags: list[str],
        is_fav: bool,
        toggle_fav_cb: Callable[[int, ctk.CTkButton], None],
        delete_cb: Callable[[int, ctk.CTkToplevel], None],
        show_similar_images_cb: Optional[
            Callable[[ImageEntry, ctk.CTkFrame], None]
        ] = None,
    ) -> None:
        super().__init__(parent)
        self._setup_window(entry)
        self._setup_dependencies(entry)
        self._setup_ui(
            entry, tags, is_fav, toggle_fav_cb, delete_cb, show_similar_images_cb
        )

    def _setup_window(self, entry: ImageEntry) -> None:
        """ウィンドウの基本設定"""
        self.lift()
        self.attributes("-topmost", True)
        self.after(100, lambda: self.attributes("-topmost", False))
        self.title(Path(entry.image_path).name)

    def _setup_dependencies(self, entry: ImageEntry) -> None:
        """依存関係の初期化"""
        self.entry: ImageEntry = entry
        self.file_ops: FileOperationManager = FileOperationManager(self)

    def _setup_ui(
        self,
        entry: ImageEntry,
        tags: list[str],
        is_fav: bool,
        toggle_fav_cb: Callable[[int, ctk.CTkButton], None],
        delete_cb: Callable[[int, ctk.CTkToplevel], None],
        show_similar_images_cb: Optional[Callable[[ImageEntry, ctk.CTkFrame], None]],
    ) -> None:
        """UI全体の構築"""
        # メインコンテナ
        container: ctk.CTkFrame = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True)

        # 左右分割
        self._setup_image_section(container, entry, is_fav, toggle_fav_cb, delete_cb)
        self._setup_content_section(container, tags, show_similar_images_cb)

    def _setup_image_section(
        self,
        container: ctk.CTkFrame,
        entry: ImageEntry,
        is_fav: bool,
        toggle_fav_cb: Callable[[int, ctk.CTkButton], None],
        delete_cb: Callable[[int, ctk.CTkToplevel], None],
    ) -> None:
        """左側：画像エリア"""
        left_frame: ctk.CTkFrame = ctk.CTkFrame(container, fg_color="transparent")
        left_frame.pack(side="left", fill="y", padx=10, pady=10)

        image_frame: ctk.CTkFrame = ctk.CTkFrame(left_frame, fg_color="transparent")
        image_frame.pack()

        # 画像表示とコピー機能
        label: ctk.CTkLabel = image_manager.load_full_image(
            image_frame, entry.image_path
        )
        label.pack(anchor="w")
        self._setup_image_copy(label)

        # ボタン配置
        self._setup_action_buttons(
            image_frame, entry.id, is_fav, toggle_fav_cb, delete_cb
        )

    def _setup_action_buttons(
        self,
        parent: ctk.CTkFrame,
        entry_id: int,
        is_fav: bool,
        toggle_fav_cb: Callable[[int, ctk.CTkButton], None],
        delete_cb: Callable[[int, ctk.CTkToplevel], None],
    ) -> None:
        """アクションボタンの配置"""
        fav_button: ctk.CTkButton = create_favorite_button(
            parent, is_fav, command=lambda: toggle_fav_cb(entry_id, fav_button)
        )
        fav_button.place(relx=1.0, rely=1.0, anchor="se", x=-12, y=-12)

        if not is_fav:
            del_button: ctk.CTkButton = create_delete_button(
                parent, command=lambda: delete_cb(entry_id, self)
            )
            del_button.place(relx=0.0, rely=1.0, anchor="sw", x=12, y=-12)

    def _setup_content_section(
        self,
        container: ctk.CTkFrame,
        tags: list[str],
        show_similar_images_cb: Optional[Callable[[ImageEntry, ctk.CTkFrame], None]],
    ) -> None:
        """右側：タグ + ギャラリー"""
        right_frame: ctk.CTkFrame = ctk.CTkFrame(container)
        right_frame.pack(side="left", fill="both", expand=True, padx=(10, 10), pady=10)

        # 上下分割
        self._setup_tags_area(right_frame, tags)
        self._setup_gallery_area(right_frame, show_similar_images_cb)

    def _setup_tags_area(self, parent: ctk.CTkFrame, tags: list[str]) -> None:
        """タグエリアの設定"""
        top_frame: ctk.CTkFrame = ctk.CTkFrame(parent, fg_color="transparent")
        top_frame.pack(fill="x", anchor="n")

        # タグ表示の初期化と更新
        def setup_tags() -> None:
            top_frame.update_idletasks()
            width: int = top_frame.winfo_width()
            if width > 1:
                self._render_tag_buttons(top_frame, tags, width - 20)
            else:
                top_frame.after(50, setup_tags)

        def on_resize(event: ctk.CTkFrame) -> None:
            if (
                not hasattr(self, "_last_width")
                or abs(event.width - self._last_width) > 10
            ):
                self._last_width = event.width
                self._render_tag_buttons(top_frame, tags, event.width - 20)

        top_frame.after(50, setup_tags)
        top_frame.bind("<Configure>", on_resize)

    def _setup_gallery_area(
        self,
        parent: ctk.CTkFrame,
        show_similar_images_cb: Optional[Callable[[ImageEntry, ctk.CTkFrame], None]],
    ) -> None:
        """ギャラリーエリア（スクロール対応）"""
        bottom_frame: ctk.CTkFrame = ctk.CTkFrame(parent)
        bottom_frame.pack(fill="both", expand=True)

        # スクロール可能なギャラリー（元のコードを使用）
        canvas_container: ctk.CTkFrame = ctk.CTkFrame(bottom_frame)
        canvas_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        canvas: ctk.CTkCanvas = ctk.CTkCanvas(canvas_container, highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)

        scrollbar: ctk.CTkScrollbar = ctk.CTkScrollbar(
            canvas_container, orientation="vertical", command=canvas.yview
        )
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollable_frame: ctk.CTkFrame = ctk.CTkFrame(canvas)
        window_id: int = canvas.create_window(
            (0, 0), window=scrollable_frame, anchor="nw"
        )

        scrollable_frame.bind(
            "<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width)
        )

        self.enable_mousewheel_scroll(canvas)

        # 類似画像の表示
        if show_similar_images_cb:
            scrollable_frame.after(
                100, lambda: show_similar_images_cb(self.entry, scrollable_frame)
            )

    def _setup_image_copy(self, widget: ctk.CTkLabel) -> None:
        """画像コピー機能の設定"""
        menu = self.create_context_menu(
            {
                "画像をコピー": lambda: self.file_ops.copy_image(self.entry.image_path),
                "ファイルパスをコピー": lambda: self.file_ops.copy_file_path(
                    self.entry.image_path
                ),
                "---": None,
                "ファイルを開く": lambda: self.file_ops.open_file(
                    self.entry.image_path
                ),
            }
        )

        widget.bind("<Button-3>", lambda e: self.show_styled_menu(menu, e))
        widget.bind(
            "<Control-c>", lambda e: self.file_ops.copy_image(self.entry.image_path)
        )
        widget.focus_set()

    def _render_tag_buttons(
        self,
        parent_frame: ctk.CTkFrame,
        tags: list[str],
        max_width: Optional[int] = None,
        padding: int = 2,
    ) -> None:
        """タグボタンの折り返し表示"""
        # 既存フレームを削除
        if hasattr(self, "tag_button_frame"):
            self.tag_button_frame.destroy()

        effective_max_width: int = max_width or max(
            200, parent_frame.winfo_width() - 20
        )

        self.tag_button_frame: ctk.CTkFrame = ctk.CTkFrame(
            parent_frame, fg_color="transparent"
        )
        self.tag_button_frame.pack(anchor="n", padx=4, pady=(0, 10), fill="x")

        # タグのレイアウト計算
        lines: list[list[str]] = self._calculate_tag_layout(
            tags, effective_max_width, padding
        )

        # ボタン作成
        self._create_tag_buttons(lines, padding)

    def _calculate_tag_layout(
        self, tags: list[str], max_width: int, padding: int
    ) -> list[list[str]]:
        """タグの行分けを計算"""
        lines: list[list[str]] = []
        current_line: list[str] = []
        current_width: int = 0
        tag_font: ctk.CTkFont = ctk.CTkFont(family="Meiryo", size=12)

        for tag in tags:
            text_width: int = tag_font.measure(tag)
            button_width: int = text_width + 15  # パディング
            total_width: int = button_width + padding

            if current_width + total_width > max_width and current_line:
                lines.append(current_line)
                current_line = [tag]
                current_width = total_width
            else:
                current_line.append(tag)
                current_width += total_width

        if current_line:
            lines.append(current_line)

        return lines

    def _create_tag_buttons(self, lines: list[list[str]], padding: int) -> None:
        """タグボタンの作成"""
        tag_font: ctk.CTkFont = ctk.CTkFont(family="Meiryo", size=12)

        for line_tags in lines:
            line_frame: ctk.CTkFrame = ctk.CTkFrame(
                self.tag_button_frame, fg_color="transparent"
            )
            line_frame.pack(anchor="w", pady=2)

            for tag in line_tags:
                btn: ctk.CTkButton = ctk.CTkButton(
                    line_frame,
                    text=tag,
                    command=lambda t=tag: self._copy_tag(t),
                    width=0,
                    height=26,
                    font=tag_font,
                    fg_color="#444444",
                    hover_color="#666666",
                    text_color="#ffffff",
                    corner_radius=6,
                )
                btn.pack(side="left", padx=(0, padding), pady=2)

    def _copy_tag(self, tag: str) -> None:
        """タグをクリップボードにコピー"""
        self.clipboard_clear()
        self.clipboard_append(tag)
        self.update()
