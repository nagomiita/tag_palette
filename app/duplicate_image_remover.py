import logging
import os
import threading
import time
import tkinter as tk
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from typing import Dict, List, Tuple

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageTk
from sklearn.metrics.pairwise import cosine_similarity

# ごみ箱削除用ライブラリ
try:
    from send2trash import send2trash

    TRASH_AVAILABLE = True
except ImportError:
    TRASH_AVAILABLE = False
    print("警告: send2trashライブラリがインストールされていません。")
    print("ごみ箱機能を使用するには: pip install send2trash")

# データベース関連のインポート
from db.engine import engine
from db.models import ImageEntry
from sqlalchemy.orm import Session

# パフォーマンス測定用のロガー設定
perf_logger = logging.getLogger("duplicate_finder_performance")
perf_logger.setLevel(logging.INFO)
if not perf_logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - PERF - %(message)s")
    handler.setFormatter(formatter)
    perf_logger.addHandler(handler)


@contextmanager
def get_session():
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


@contextmanager
def measure_query_time(query_name: str):
    """クエリ実行時間を測定するコンテキストマネージャ"""
    start_time = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start_time
        perf_logger.info(f"QUERY [{query_name}]: {elapsed:.4f}s")


@dataclass
class DuplicateGroup:
    """重複画像グループの情報"""

    images: List[Dict]
    similarity_score: float
    recommended_keep: Dict  # 保持推奨画像
    recommended_delete: List[Dict]  # 削除推奨画像


class DuplicateImageRemover:
    def __init__(self):
        self.window = ctk.CTk()
        self.window.title("重複画像削除ツール")
        self.window.geometry("1400x900")

        # 変数
        self.similarity_threshold = ctk.DoubleVar(value=0.95)
        self.duplicate_groups: List[DuplicateGroup] = []
        self.current_group_index = 0
        self.selected_images = set()
        self.use_trash = ctk.BooleanVar(value=TRASH_AVAILABLE)  # ごみ箱使用フラグ

        # UI初期化
        self.setup_ui()

    def setup_ui(self):
        """UI設定"""
        # メインフレーム
        main_frame = ctk.CTkFrame(self.window)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # コントロールパネル
        self.setup_control_panel(main_frame)

        # 画像表示エリア
        self.setup_image_display(main_frame)

        # ボタンパネル
        self.setup_button_panel(main_frame)

    def setup_control_panel(self, parent):
        """コントロールパネル設定"""
        control_frame = ctk.CTkFrame(parent)
        control_frame.pack(fill="x", padx=5, pady=5)

        # 検索モード選択
        mode_frame = ctk.CTkFrame(control_frame)
        mode_frame.pack(side="left", padx=5)

        self.search_mode = ctk.StringVar(value="exact_tags")

        mode_radio1 = ctk.CTkRadioButton(
            mode_frame,
            text="同一タグ検索",
            variable=self.search_mode,
            value="exact_tags",
        )
        mode_radio1.pack(side="top", padx=2, pady=2)

        mode_radio2 = ctk.CTkRadioButton(
            mode_frame, text="類似度検索", variable=self.search_mode, value="similarity"
        )
        mode_radio2.pack(side="top", padx=2, pady=2)

        # 類似度閾値設定（類似度検索時のみ有効）
        similarity_frame = ctk.CTkFrame(control_frame)
        similarity_frame.pack(side="left", padx=5)

        ctk.CTkLabel(similarity_frame, text="類似度閾値:").pack(side="top", padx=2)
        self.similarity_slider = ctk.CTkSlider(
            similarity_frame,
            from_=0.80,
            to=1.00,
            variable=self.similarity_threshold,
            number_of_steps=19,
            width=150,
        )
        self.similarity_slider.pack(side="top", padx=2)

        self.similarity_label = ctk.CTkLabel(
            similarity_frame, text=f"{self.similarity_threshold.get():.2f}"
        )
        self.similarity_label.pack(side="top", padx=2)

        # 閾値更新時のコールバック
        self.similarity_slider.configure(command=self.update_similarity_label)

        # モード変更時のUI更新
        self.search_mode.trace("w", self.on_mode_change)

        # 検索ボタン
        search_btn = ctk.CTkButton(
            control_frame, text="重複検索実行", command=self.search_duplicates
        )
        search_btn.pack(side="left", padx=10)

        # 進行状況
        self.progress_label = ctk.CTkLabel(control_frame, text="")
        self.progress_label.pack(side="right", padx=5)

    def setup_image_display(self, parent):
        """画像表示エリア設定"""
        display_frame = ctk.CTkFrame(parent)
        display_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # 上部情報表示
        info_frame = ctk.CTkFrame(display_frame)
        info_frame.pack(fill="x", padx=5, pady=5)

        self.group_info_label = ctk.CTkLabel(
            info_frame, text="重複グループ情報が表示されます"
        )
        self.group_info_label.pack(pady=5)

        # 画像表示エリア（スクロール可能）
        self.image_scroll_frame = ctk.CTkScrollableFrame(display_frame, height=500)
        self.image_scroll_frame.pack(fill="both", expand=True, padx=5, pady=5)

    def setup_button_panel(self, parent):
        """ボタンパネル設定"""
        button_frame = ctk.CTkFrame(parent)
        button_frame.pack(fill="x", padx=5, pady=5)

        # ナビゲーションボタン
        nav_frame = ctk.CTkFrame(button_frame)
        nav_frame.pack(side="left", padx=5)

        self.prev_btn = ctk.CTkButton(
            nav_frame,
            text="← 前のグループ",
            command=self.show_previous_group,
            state="disabled",
        )
        self.prev_btn.pack(side="left", padx=2)

        self.next_btn = ctk.CTkButton(
            nav_frame,
            text="次のグループ →",
            command=self.show_next_group,
            state="disabled",
        )
        self.next_btn.pack(side="left", padx=2)

        # 操作ボタン
        action_frame = ctk.CTkFrame(button_frame)
        action_frame.pack(side="right", padx=5)

        # ごみ箱設定チェックボックス
        if TRASH_AVAILABLE:
            trash_checkbox = ctk.CTkCheckBox(
                action_frame, text="ごみ箱に移動", variable=self.use_trash
            )
            trash_checkbox.pack(side="left", padx=2)
        else:
            # send2trashが利用できない場合の警告表示
            warning_label = ctk.CTkLabel(
                action_frame, text="⚠️ ごみ箱機能無効", text_color="orange"
            )
            warning_label.pack(side="left", padx=2)

        # 選択状態管理ボタン
        selection_frame = ctk.CTkFrame(action_frame)
        selection_frame.pack(side="left", padx=5)

        self.clear_btn = ctk.CTkButton(
            selection_frame,
            text="選択解除",
            command=self.clear_all_selections,
            fg_color="gray",
            width=80,
        )
        self.clear_btn.pack(side="top", padx=1, pady=1)

        self.selection_count_label = ctk.CTkLabel(
            selection_frame, text="選択: 0件", font=("Arial", 10)
        )
        self.selection_count_label.pack(side="top", padx=1, pady=1)

        # 削除ボタン群
        delete_frame = ctk.CTkFrame(action_frame)
        delete_frame.pack(side="left", padx=5)

        self.delete_current_btn = ctk.CTkButton(
            delete_frame,
            text="このグループの選択画像を削除",
            command=self.delete_current_group_selected,
            fg_color="red",
            width=180,
        )
        self.delete_current_btn.pack(side="top", padx=1, pady=1)

        self.delete_all_btn = ctk.CTkButton(
            delete_frame,
            text="全選択画像を削除",
            command=self.delete_selected_images,
            fg_color="darkred",
            width=180,
        )
        self.delete_all_btn.pack(side="top", padx=1, pady=1)

        auto_delete_btn = ctk.CTkButton(
            action_frame,
            text="推奨削除実行",
            command=self.auto_delete_duplicates,
            fg_color="orange",
        )
        auto_delete_btn.pack(side="left", padx=2)

    def update_similarity_label(self, value):
        """類似度ラベル更新"""
        self.similarity_label.configure(text=f"{float(value):.2f}")

    def on_mode_change(self, *args):
        """検索モード変更時の処理"""
        is_similarity_mode = self.search_mode.get() == "similarity"
        # 類似度スライダーの有効/無効切り替え
        state = "normal" if is_similarity_mode else "disabled"
        self.similarity_slider.configure(state=state)

    def get_image_resolution(self, image_path: str) -> Tuple[int, int]:
        """画像の解像度を取得"""
        try:
            with Image.open(image_path) as img:
                return img.size  # (width, height)
        except Exception as e:
            print(f"解像度取得エラー {image_path}: {e}")
            return (0, 0)

    def calculate_priority_score(self, image_data: Dict) -> float:
        """画像の優先度スコアを計算"""
        score = 0.0

        # お気に入りフラグ（重み: 1000）- 最重要
        if image_data.get("is_favorite", False):
            score += 1000.0

        # 解像度（重み: 1、正規化）
        width, height = image_data.get("resolution", (0, 0))
        if width > 0 and height > 0:
            resolution_score = (width * height) / (1920 * 1080)  # 1080pを基準に正規化
            score += resolution_score

        # ビューカウント（重み: 0.1）
        view_count = image_data.get("view_count", 0)
        score += view_count * 0.1

        # ファイルサイズ（重み: 0.01）
        try:
            file_size = os.path.getsize(image_data["image_path"])
            score += (file_size / (1024 * 1024)) * 0.01  # MB単位
        except:
            pass

        return score

    def load_all_image_data_with_tags(self) -> List[Dict]:
        """全画像データとタグ情報を取得"""
        perf_logger.info("画像データ・タグ情報取得開始")

        with get_session() as session:
            with measure_query_time("get_images_with_tags"):
                # 画像ごとのタグリストを取得
                query = session.query(ImageEntry).all()

            perf_logger.info(f"データベースから{len(query)}件の画像を取得")

            image_data = []
            processed_count = 0

            with measure_query_time(f"process_image_tags_{len(query)}"):
                for entry in query:
                    try:
                        # ファイル存在確認
                        if not os.path.exists(entry.image_path):
                            continue

                        # 解像度取得
                        resolution = self.get_image_resolution(entry.image_path)
                        if resolution == (0, 0):
                            continue

                        # タグ情報を取得
                        tag_names = []
                        for image_tag in entry.image_tags:
                            if image_tag.tag and image_tag.tag.name:
                                tag_names.append(image_tag.tag.name)

                        # タグでソートして一意性を確保
                        tag_names = sorted(set(tag_names))

                        # 埋め込みベクトル取得（類似度検索用）
                        embedding = None
                        if entry.tag_embedding and "," in entry.tag_embedding:
                            try:
                                embedding = np.array(
                                    [float(x) for x in entry.tag_embedding.split(",")]
                                )
                            except:
                                pass

                        image_info = {
                            "id": entry.id,
                            "image_path": entry.image_path,
                            "thumbnail_path": entry.thumbnail_path
                            if entry.thumbnail_path
                            else entry.image_path,
                            "is_favorite": entry.is_favorite
                            if entry.is_favorite is not None
                            else False,
                            "resolution": resolution,
                            "view_count": entry.view_count
                            if entry.view_count is not None
                            else 0,
                            "created_at": entry.created_at,
                            "registered_at": entry.registered_at,
                            "tag_names": tag_names,
                            "tag_signature": "|".join(tag_names),  # タグの一意識別子
                            "embedding": embedding,
                        }

                        # 優先度スコア計算
                        image_info["priority_score"] = self.calculate_priority_score(
                            image_info
                        )
                        image_data.append(image_info)

                        processed_count += 1

                        # 進行状況表示（100件ごと）
                        if processed_count % 100 == 0:
                            self.window.after(
                                0,
                                lambda p=processed_count,
                                t=len(query): self.progress_label.configure(
                                    text=f"処理中: {p}/{t}"
                                ),
                            )

                    except Exception as e:
                        perf_logger.error(f"画像データ処理エラー {entry.id}: {e}")
                        continue

            perf_logger.info(f"処理完了: {len(image_data)}件の有効な画像データ")
            return image_data

    def find_exact_tag_duplicates(self, image_data: List[Dict]) -> List[DuplicateGroup]:
        """同一タグを持つ重複グループを検出"""
        perf_logger.info("同一タグ重複検索開始")

        # タグ署名でグループ化
        tag_groups = {}
        for image in image_data:
            tag_signature = image["tag_signature"]
            if tag_signature:  # 空のタグは除外
                if tag_signature not in tag_groups:
                    tag_groups[tag_signature] = []
                tag_groups[tag_signature].append(image)

        duplicate_groups = []

        # 2件以上の画像を持つグループのみ処理
        for tag_signature, images in tag_groups.items():
            if len(images) >= 2:
                # 優先度でソート（降順）
                images.sort(key=lambda x: x["priority_score"], reverse=True)

                # 最高優先度を保持、残りを削除対象
                recommended_keep = images[0]
                recommended_delete = images[1:]

                duplicate_group = DuplicateGroup(
                    images=images,
                    similarity_score=1.0,  # 完全一致
                    recommended_keep=recommended_keep,
                    recommended_delete=recommended_delete,
                )

                duplicate_groups.append(duplicate_group)

        perf_logger.info(f"同一タグ重複グループ: {len(duplicate_groups)}件")
        return duplicate_groups

    def find_similarity_duplicates(
        self, image_data: List[Dict], threshold: float
    ) -> List[DuplicateGroup]:
        """埋め込みベクトルの類似度で重複グループを検出"""
        perf_logger.info("類似度重複検索開始")

        # 埋め込みベクトルが存在する画像のみフィルタ
        valid_images = [img for img in image_data if img.get("embedding") is not None]

        if len(valid_images) < 2:
            return []

        # 埋め込みベクトルを抽出
        embeddings = np.array([img["embedding"] for img in valid_images])

        # コサイン類似度計算
        similarity_matrix = cosine_similarity(embeddings)

        duplicate_groups = []
        processed = set()

        for i in range(len(valid_images)):
            if i in processed:
                continue

            # 類似度が閾値以上の画像を検索
            similar_indices = np.where(similarity_matrix[i] >= threshold)[0]
            similar_indices = [
                idx for idx in similar_indices if idx not in processed and idx != i
            ]

            if len(similar_indices) > 0:
                # グループ作成
                group_images = [valid_images[i]] + [
                    valid_images[idx] for idx in similar_indices
                ]

                # 優先度でソート（降順）
                group_images.sort(key=lambda x: x["priority_score"], reverse=True)

                # 最高優先度を保持、残りを削除対象
                recommended_keep = group_images[0]
                recommended_delete = group_images[1:]

                # 類似度スコア（最小値）
                min_similarity = min(
                    [similarity_matrix[i][idx] for idx in similar_indices]
                )

                duplicate_group = DuplicateGroup(
                    images=group_images,
                    similarity_score=min_similarity,
                    recommended_keep=recommended_keep,
                    recommended_delete=recommended_delete,
                )

                duplicate_groups.append(duplicate_group)

                # 処理済みマーク
                processed.add(i)
                for idx in similar_indices:
                    processed.add(idx)

        perf_logger.info(f"類似度重複グループ: {len(duplicate_groups)}件")
        return duplicate_groups

    def search_duplicates(self):
        """重複検索実行"""

        def search_thread():
            try:
                self.progress_label.configure(text="画像データ読み込み中...")
                image_data = self.load_all_image_data_with_tags()

                search_mode = self.search_mode.get()

                if search_mode == "exact_tags":
                    self.progress_label.configure(text="同一タグ検索中...")
                    self.duplicate_groups = self.find_exact_tag_duplicates(image_data)
                else:  # similarity
                    self.progress_label.configure(text="類似度検索中...")
                    threshold = self.similarity_threshold.get()
                    self.duplicate_groups = self.find_similarity_duplicates(
                        image_data, threshold
                    )

                # UI更新
                self.window.after(0, self.update_duplicate_display)

            except Exception as e:
                error_msg = f"重複検索エラー: {e}"
                perf_logger.error(error_msg)
                self.window.after(0, lambda: messagebox.showerror("エラー", error_msg))
            finally:
                self.window.after(0, lambda: self.progress_label.configure(text=""))

        threading.Thread(target=search_thread, daemon=True).start()

    def update_duplicate_display(self):
        """重複表示更新"""
        if not self.duplicate_groups:
            messagebox.showinfo("結果", "重複画像は見つかりませんでした。")
            return

        self.current_group_index = 0
        # 新しい検索結果では選択状態をリセット
        self.selected_images.clear()
        self.show_current_group()
        self.update_navigation_buttons()

    def show_current_group(self):
        """現在のグループを表示"""
        if not self.duplicate_groups or self.current_group_index >= len(
            self.duplicate_groups
        ):
            return

        group = self.duplicate_groups[self.current_group_index]

        # グループ情報更新
        search_mode_text = (
            "同一タグ" if self.search_mode.get() == "exact_tags" else "類似度"
        )
        info_text = (
            f"[{search_mode_text}検索] グループ {self.current_group_index + 1}/{len(self.duplicate_groups)} | "
            f"一致度: {group.similarity_score:.3f} | "
            f"画像数: {len(group.images)}"
        )
        self.group_info_label.configure(text=info_text)

        # 画像表示エリアをクリア
        for widget in self.image_scroll_frame.winfo_children():
            widget.destroy()

        # 画像を表示
        for i, image_info in enumerate(group.images):
            self.create_image_widget(image_info, i == 0)  # 最初の画像は保持推奨

        # 選択数表示を更新
        self.update_selection_count()

    def create_image_widget(self, image_info: Dict, is_recommended_keep: bool):
        """画像ウィジェットを作成"""
        # メインフレーム
        frame_color = "green" if is_recommended_keep else "red"
        image_frame = ctk.CTkFrame(
            self.image_scroll_frame, fg_color=frame_color, corner_radius=10
        )
        image_frame.pack(fill="x", padx=5, pady=5)

        # 画像とメタデータを横並び
        content_frame = ctk.CTkFrame(image_frame)
        content_frame.pack(fill="x", padx=5, pady=5)

        # 画像表示
        try:
            # サムネイル読み込み
            thumbnail_path = image_info.get("thumbnail_path", image_info["image_path"])
            if os.path.exists(thumbnail_path):
                img_path = thumbnail_path
            else:
                img_path = image_info["image_path"]

            with Image.open(img_path) as img:
                # リサイズ（最大200x200）
                img.thumbnail((200, 200))
                photo = ImageTk.PhotoImage(img)

                img_label = tk.Label(content_frame, image=photo)
                img_label.image = photo  # 参照保持
                img_label.pack(side="left", padx=5, pady=5)
        except Exception as e:
            img_label = ctk.CTkLabel(content_frame, text=f"画像読み込みエラー\n{e}")
            img_label.pack(side="left", padx=5, pady=5)

        # メタデータ表示
        meta_frame = ctk.CTkFrame(content_frame)
        meta_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        # ファイル情報
        file_name = os.path.basename(image_info["image_path"])
        width, height = image_info["resolution"]
        file_size = self.get_file_size(image_info["image_path"])
        view_count = image_info.get("view_count", 0)
        created_at = image_info.get("created_at", "Unknown")
        tag_names = image_info.get("tag_names", [])

        # タグ情報を整形（長すぎる場合は省略）
        if len(tag_names) > 0:
            tag_display = ", ".join(tag_names[:10])
            if len(tag_names) > 10:
                tag_display += f" ... (+{len(tag_names) - 10}個)"
        else:
            tag_display = "タグなし"

        info_text = f"""
ファイル名: {file_name}
解像度: {width}x{height}
ファイルサイズ: {file_size}
閲覧回数: {view_count}回
お気に入り: {"✓" if image_info["is_favorite"] else "✗"}
作成日時: {created_at}
タグ数: {len(tag_names)}個
タグ: {tag_display}
優先度スコア: {image_info["priority_score"]:.2f}
推奨: {"保持" if is_recommended_keep else "削除"}
        """.strip()

        info_label = ctk.CTkLabel(meta_frame, text=info_text, justify="left")
        info_label.pack(anchor="w", padx=5, pady=5)

        # 選択チェックボックス
        var = tk.BooleanVar()

        # 既存の選択状態を復元
        if image_info["id"] in self.selected_images:
            var.set(True)
        elif (
            not is_recommended_keep
        ):  # 削除推奨の場合はデフォルトでチェック（新規のみ）
            var.set(True)
            self.selected_images.add(image_info["id"])

        checkbox = ctk.CTkCheckBox(
            meta_frame,
            text="削除対象に選択",
            variable=var,
            command=lambda: self.toggle_selection(image_info["id"], var.get()),
        )
        checkbox.pack(anchor="w", padx=5, pady=2)

    def get_file_size(self, file_path: str) -> str:
        """ファイルサイズを取得（人間が読みやすい形式）"""
        try:
            size = os.path.getsize(file_path)
            for unit in ["B", "KB", "MB", "GB"]:
                if size < 1024.0:
                    return f"{size:.1f} {unit}"
                size /= 1024.0
            return f"{size:.1f} TB"
        except:
            return "不明"

    def toggle_selection(self, image_id: int, selected: bool):
        """画像選択状態を切り替え"""
        if selected:
            self.selected_images.add(image_id)
        else:
            self.selected_images.discard(image_id)

        # 選択数表示を更新
        self.update_selection_count()

    def update_selection_count(self):
        """選択数表示を更新"""
        total_count = len(self.selected_images)

        # 現在のグループでの選択数も計算
        current_group_count = 0
        if self.duplicate_groups and self.current_group_index < len(
            self.duplicate_groups
        ):
            current_group = self.duplicate_groups[self.current_group_index]
            current_group_ids = {img["id"] for img in current_group.images}
            current_group_count = len(self.selected_images & current_group_ids)

        # ラベル更新
        self.selection_count_label.configure(
            text=f"選択: {total_count}件\n(現在G: {current_group_count}件)"
        )

        # ボタンの有効/無効制御
        self.delete_current_btn.configure(
            state="normal" if current_group_count > 0 else "disabled"
        )
        self.delete_all_btn.configure(state="normal" if total_count > 0 else "disabled")
        self.clear_btn.configure(state="normal" if total_count > 0 else "disabled")

    def clear_all_selections(self):
        """すべての選択を解除"""
        self.selected_images.clear()
        self.update_selection_count()
        # 現在のグループを再表示して選択状態をリセット
        self.show_current_group()

    def delete_current_group_selected(self):
        """現在のグループの選択画像のみを削除"""
        if not self.duplicate_groups or self.current_group_index >= len(
            self.duplicate_groups
        ):
            messagebox.showwarning("警告", "表示できるグループがありません。")
            return

        current_group = self.duplicate_groups[self.current_group_index]
        current_group_ids = {img["id"] for img in current_group.images}

        # 現在のグループの選択画像のみフィルタ
        current_selected = self.selected_images & current_group_ids

        if not current_selected:
            messagebox.showwarning(
                "警告", "現在のグループで選択された画像がありません。"
            )
            return

        use_trash = self.use_trash.get() and TRASH_AVAILABLE
        deletion_method = "ごみ箱に移動" if use_trash else "完全削除"

        result = messagebox.askyesno(
            "確認",
            f"現在のグループの{len(current_selected)}個の画像を{deletion_method}しますか？\n\n"
            f"削除方法: {deletion_method}\n"
            f"{'ごみ箱から復元可能です。' if use_trash else 'この操作は取り消せません。'}\n\n"
            f"※ 他のグループの選択画像は削除されません",
        )

        if result:
            self.execute_deletion(list(current_selected))

    def show_previous_group(self):
        """前のグループを表示"""
        if self.current_group_index > 0:
            self.current_group_index -= 1
            self.show_current_group()
            self.update_navigation_buttons()

    def show_next_group(self):
        """次のグループを表示"""
        if self.current_group_index < len(self.duplicate_groups) - 1:
            self.current_group_index += 1
            self.show_current_group()
            self.update_navigation_buttons()

    def update_navigation_buttons(self):
        """ナビゲーションボタンの状態更新"""
        self.prev_btn.configure(
            state="normal" if self.current_group_index > 0 else "disabled"
        )
        self.next_btn.configure(
            state="normal"
            if self.current_group_index < len(self.duplicate_groups) - 1
            else "disabled"
        )

    def delete_selected_images(self):
        """選択された画像を削除（全グループ対象）"""
        if not self.selected_images:
            messagebox.showwarning("警告", "削除する画像が選択されていません。")
            return

        use_trash = self.use_trash.get() and TRASH_AVAILABLE
        deletion_method = "ごみ箱に移動" if use_trash else "完全削除"

        result = messagebox.askyesno(
            "確認",
            f"全グループで選択された{len(self.selected_images)}個の画像を{deletion_method}しますか？\n\n"
            f"削除方法: {deletion_method}\n"
            f"{'ごみ箱から復元可能です。' if use_trash else 'この操作は取り消せません。'}\n\n"
            f"※ 全てのグループの選択画像が対象です",
        )

        if result:
            self.execute_deletion(list(self.selected_images))

    def auto_delete_duplicates(self):
        """推奨削除を自動実行"""
        if not self.duplicate_groups:
            return

        delete_count = sum(
            len(group.recommended_delete) for group in self.duplicate_groups
        )
        use_trash = self.use_trash.get() and TRASH_AVAILABLE
        deletion_method = "ごみ箱に移動" if use_trash else "完全削除"

        result = messagebox.askyesno(
            "確認",
            f"推奨削除により{delete_count}個の画像を{deletion_method}しますか？\n\n"
            f"削除方法: {deletion_method}\n"
            f"{'ごみ箱から復元可能です。' if use_trash else 'この操作は取り消せません。'}",
        )

        if result:
            delete_ids = []
            for group in self.duplicate_groups:
                delete_ids.extend([img["id"] for img in group.recommended_delete])
            self.execute_deletion(delete_ids)

    def delete_image_files(
        self, image_path: str, thumbnail_path: str
    ) -> Tuple[bool, str]:
        """画像とサムネイルのファイルを削除（ごみ箱対応）"""
        use_trash = self.use_trash.get() and TRASH_AVAILABLE
        deletion_method = "ごみ箱に移動" if use_trash else "完全削除"

        deleted_files = []
        failed_files = []

        for path_str in [image_path, thumbnail_path]:
            if not path_str:
                continue

            path = Path(path_str)
            try:
                if path.exists():
                    if use_trash:
                        # ごみ箱に移動
                        send2trash(str(path))
                        perf_logger.info(f"ごみ箱移動: {path}")
                    else:
                        # 完全削除
                        path.unlink()
                        perf_logger.info(f"完全削除: {path}")
                    deleted_files.append(str(path))
                else:
                    perf_logger.warning(f"ファイルが存在しません: {path}")
            except Exception as e:
                error_msg = f"ファイル削除エラー {path}: {e}"
                perf_logger.error(error_msg)
                failed_files.append(str(path))

        # 結果メッセージ作成
        if failed_files:
            status_msg = f"{deletion_method}失敗: {len(failed_files)}件"
        else:
            status_msg = f"{deletion_method}成功: {len(deleted_files)}件"

        return len(failed_files) == 0, status_msg

    def execute_deletion(self, image_ids: List[int]):
        """実際の削除実行"""

        def delete_thread():
            try:
                use_trash = self.use_trash.get() and TRASH_AVAILABLE
                deletion_method = "ごみ箱移動" if use_trash else "完全削除"

                self.window.after(
                    0,
                    lambda: self.progress_label.configure(
                        text=f"{deletion_method}処理中..."
                    ),
                )

                deleted_count = 0
                failed_count = 0
                file_results = []

                for i, image_id in enumerate(image_ids):
                    try:
                        with get_session() as session:
                            with measure_query_time(f"get_image_for_delete_{image_id}"):
                                entry = (
                                    session.query(ImageEntry)
                                    .filter_by(id=image_id)
                                    .first()
                                )

                            if entry:
                                # ファイル削除
                                file_success, file_msg = self.delete_image_files(
                                    entry.image_path, entry.thumbnail_path
                                )
                                file_results.append(file_msg)

                                if file_success:
                                    # DB削除（ファイル削除成功時のみ）
                                    with measure_query_time(
                                        f"delete_db_entry_{image_id}"
                                    ):
                                        session.delete(entry)
                                        session.commit()
                                    deleted_count += 1
                                    perf_logger.info(f"画像削除完了: ID={image_id}")
                                else:
                                    failed_count += 1
                                    perf_logger.warning(
                                        f"ファイル削除失敗によりDB削除をスキップ: ID={image_id}"
                                    )
                            else:
                                failed_count += 1
                                perf_logger.warning(
                                    f"画像が見つかりません: ID={image_id}"
                                )

                        # 進行状況更新
                        progress = f"{deletion_method}中: {i + 1}/{len(image_ids)}"
                        self.window.after(
                            0, lambda p=progress: self.progress_label.configure(text=p)
                        )

                    except Exception as e:
                        failed_count += 1
                        perf_logger.error(f"削除エラー ID={image_id}: {e}")

                # 完了メッセージ
                message = f"{deletion_method}完了\n"
                message += f"成功: {deleted_count}件"
                if failed_count > 0:
                    message += f"\n失敗: {failed_count}件"

                # ごみ箱使用時の追加情報
                if use_trash and deleted_count > 0:
                    message += "\n\n💡 ごみ箱から復元可能です"

                # 削除された画像IDを選択セットからも除去
                for image_id in image_ids:
                    self.selected_images.discard(image_id)

                self.window.after(0, lambda: messagebox.showinfo("削除結果", message))
                self.window.after(0, lambda: self.progress_label.configure(text=""))

                # 重複グループから削除された画像を除去
                self.window.after(0, self.remove_deleted_from_groups)

            except Exception as e:
                error_msg = f"削除処理エラー: {e}"
                perf_logger.error(error_msg)
                self.window.after(0, lambda: messagebox.showerror("エラー", error_msg))
                self.window.after(0, lambda: self.progress_label.configure(text=""))

        threading.Thread(target=delete_thread, daemon=True).start()

    def remove_deleted_from_groups(self):
        """削除された画像を重複グループから除去"""
        updated_groups = []
        for group in self.duplicate_groups:
            # 削除されていない画像のみ残す
            remaining_images = []
            for img in group.images:
                if os.path.exists(img["image_path"]):
                    remaining_images.append(img)

            # 2件以上残っている場合のみグループとして保持
            if len(remaining_images) >= 2:
                # 新しい推奨を再計算
                remaining_images.sort(key=lambda x: x["priority_score"], reverse=True)
                group.images = remaining_images
                group.recommended_keep = remaining_images[0]
                group.recommended_delete = remaining_images[1:]
                updated_groups.append(group)

        self.duplicate_groups = updated_groups

        # 現在のインデックスが範囲外になった場合の調整
        if self.current_group_index >= len(self.duplicate_groups):
            self.current_group_index = max(0, len(self.duplicate_groups) - 1)

        # 表示更新
        if self.duplicate_groups:
            self.show_current_group()
            self.update_navigation_buttons()
        else:
            # すべてのグループが削除された場合
            for widget in self.image_scroll_frame.winfo_children():
                widget.destroy()
            self.group_info_label.configure(text="重複画像がすべて処理されました")
            self.update_navigation_buttons()

    def run(self):
        """アプリケーション実行"""
        self.window.mainloop()


if __name__ == "__main__":
    # send2trashの利用可能性チェック
    if not TRASH_AVAILABLE:
        print("\n" + "=" * 50)
        print("⚠️  ごみ箱機能が利用できません")
        print("=" * 50)
        print("ごみ箱機能を有効にするには以下をインストールしてください:")
        print("pip install send2trash")
        print("\n現在は完全削除モードで動作します。")
        print("=" * 50 + "\n")

    # customtkinterの外観設定
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = DuplicateImageRemover()
    app.run()
