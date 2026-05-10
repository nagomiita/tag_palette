# tag_palette 公開 API / CLI インベントリ

eagle backend への統合検討の前提資料。**現状（リポジトリの今）が何を外に晒しているか**を機械的に列挙したもので、設計上の「あるべき姿」は含まない。

調査基準時点: `tag-generator` ブランチ HEAD。

---

## 1. パッケージ公開 API

### 1.1 トップレベル `tag_palette.*`

[`src/tag_palette/__init__.py`](../src/tag_palette/__init__.py) で `__all__` にエクスポートされている関数。これが現状の「ライブラリとしての公開契約」。

| シンボル | 種別 | 実装場所 |
|---|---|---|
| `TagResult` | dataclass | [media/tagger.py](../src/tag_palette/media/tagger.py) |
| `generate_tags` | fn | media/tagger.py |
| `generate_tags_batch` | fn | media/tagger.py |
| `get_translation_for_tag` | fn | [shared/translations.py](../src/tag_palette/shared/translations.py) |
| `text_translate` | fn | shared/translations.py |
| `translate_tag` / `translate_tags` | fn | shared/translations.py |
| `load_translation_cache` / `save_translation_cache` | fn | shared/translations.py |
| `is_japanese` / `is_preferably_japanese` | fn | shared/translations.py |
| `CATEGORY_ID_TO_NAME` | const | [media/categorize.py](../src/tag_palette/media/categorize.py) |
| `get_tag_category` | fn | media/categorize.py |
| `get_genres` | fn | [media/genre.py](../src/tag_palette/media/genre.py) |
| `tags_to_embedding` | fn | [shared/embedding.py](../src/tag_palette/shared/embedding.py) |
| `embedding_to_base64` / `base64_to_embedding` | fn | shared/embedding.py |
| `load_tag_embeddings` / `save_tag_embeddings` | fn | shared/embedding.py |
| `is_sensitive_by_ratings` | fn | [media/sensitive.py](../src/tag_palette/media/sensitive.py) |
| `is_sensitive_by_anime_rating` | fn | media/sensitive.py |
| `get_anime_rating` | fn | media/sensitive.py |
| `detect_sensitive` | fn | media/sensitive.py |

**副作用:** import 時に `HF_HUB_OFFLINE=1` を環境変数に設定（既存値があれば尊重）。

### 1.2 サブモジュール（`__all__` 未定義 = 慣習的な公開 API）

`tag_palette` のトップレベル `__init__.py` から再エクスポートされていないが、`main.py` 等から直接 import されているため**事実上の公開 API**。

#### `tag_palette.schemas` ★ 共有契約
[schemas.py](../src/tag_palette/schemas.py) — torch を import しない軽量 Pydantic モデル。FastAPI 側との共有を意図して分離済み。

| クラス | 役割 |
|---|---|
| `MediaType` (Enum) | `image` / `manga` / `video` / `audio` / `novel` |
| `MediaPalette` | 画像・動画・漫画の `tag_palette.json` ルート |
| `PanelSchema`, `TextSchema` | 漫画コマ・テキスト |
| `AudioType` (Enum) | `bgm` / `se` / `voice` |
| `AudioPalette` | 音声の `tag_palette.json` ルート |
| `ChunkSchema` | 小説チャンク |
| `NovelPalette` | 小説の `tag_palette.json` ルート |
| `TagPaletteFile` | `media_type` で判別する union パーサ |

#### `tag_palette.media.*`
| モジュール | 公開関数（先頭 `_` 除く） |
|---|---|
| `tagger` | `generate_tags`, `generate_tags_batch`, `TagResult`, モデル定数 (`WD14_MODELS` ほか) |
| `categorize` | `get_tag_category`, `CATEGORY_ID_TO_NAME` |
| `genre` | `get_genres` |
| `sensitive` | `is_sensitive_by_ratings`, `is_sensitive_by_anime_rating`, `get_anime_rating`, `detect_sensitive` |
| `eagle_scanner` | `EagleImage`, `is_image_file`, `is_eagle_audio_file`, `is_eagle_novel_file`, `is_manga_image`, `is_eagle_html_file`, `find_eagle_images` |
| `tag_writer` | `write_tags_to_eagle`, `detect_genre`, `get_genre_ja` |
| `image_processor` | `convert_heic_to_webp`, `ensure_thumbnail` |
| `pose_embedding` | `keypoints_to_vector`, `extract_pose_embedding`, `pose_similarity`, `embedding_to_bytes`, `bytes_to_embedding` |

#### `tag_palette.manga.*`
| モジュール | 公開関数 |
|---|---|
| `analyzer` | `analyze_manga_page`, `extract_panel_images`, `PanelInfo`, `TextInfo`, `MangaPageResult` |
| `ndlocr` | `recognize_page`, `OcrLine` |
| `tag_writer` | `write_manga_to_eagle` |

#### `tag_palette.audio.*`
| モジュール | 公開関数 |
|---|---|
| `tagger` | `generate_audio_tags`, `is_audio_file`, `detect_type_from_path`, `AudioType`, `AudioTagResult` |
| `labels_ja` | `get_japanese_description` |
| `tag_writer` | `write_audio_tags_to_eagle` |

#### `tag_palette.novel.*`
| モジュール | 公開関数 |
|---|---|
| `chunker` | `chunk_text`, `split_by_kind`, `Chunk` |
| `morpheme` | `extract_morphemes` |
| `embedding` | `generate_embedding`, `save_embedding`, `load_embedding`, `load_all_embeddings`, `search_similar`, `embed_chunks`, `main` |
| `pdf_parser` | `parse_pdf`, `parse_pdf_as_series`, `NovelPdf`, `NovelPdfChapter`, `NovelPdfSeries` |
| `ingest_local` | `ingest_txt_file`, `ingest_pdf_file`, `ingest_file`, `ingest_files`, `ingest_directory`, `main` |
| `label_tagger` | `sync_label_tags`, `main` |
| `tag_writer` | `write_novel_to_eagle` |
| `translate_chinese` | `translate_file`, `main` |

#### `tag_palette.importer.*`
| モジュール | 公開関数 |
|---|---|
| `csv_loader` | `load_categories`, `load_danbooru_tags`, `load_genres`, `load_category_rules`, `match_category_rule`, `load_translation_cache` |
| `models` | `TagPaletteEntry`, `AudioPaletteEntry`, `NovelPaletteEntry`, `DanbooruTag`, `CategoryEntry`, `GenreEntry`, `CategoryRule` |
| `reader` | `load_last_import`, `save_last_import`, `load_tag_palettes` |
| `media_importer` | `import_entries`, `sync_master_data`, `sync_tag_embeddings` |
| `audio_importer` | `import_audio_entries` |
| `novel_importer` | `import_novel_entries` |
| `desc_backfill` | `backfill_desc_text_ollama`, `recompute_desc_embedding`, `post_import_desc`, 定数 `OLLAMA_DEFAULT_HOST` / `OLLAMA_DEFAULT_MODEL` |
| `utils` | （内部用のみ） |

#### `tag_palette.shared.*`
| モジュール | 公開関数 |
|---|---|
| `csv_reader` | `load_clean_tag_csv` |
| `device` | `get_torch_device`, `get_onnx_device`, `get_onnx_providers` |
| `embedding` | （上述、`__init__.py` 経由で公開） |
| `env_config` | `get_image_dir`, `get_db_path`, `get_api_url`, `get_ollama_hosts` |
| `run_state` | `setup_logging`, `load_last_run`, `save_last_run` |
| `translations` | （上述、`__init__.py` 経由で公開） |

---

## 2. CLI スクリプト

リポジトリルート直下に置かれた、エントリポイントとして直接 `python` 実行されるスクリプト。

### 2.1 [`main.py`](../main.py) — Eagle ライブラリのタグ一括生成
`Eagle ライブラリの images ディレクトリをスキャンし、画像・音声に対してタグを生成して metadata.json / tag_palette.json に書き戻す`

| 引数 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `--image-dir` | △ | `EAGLE_IMAGE_DIR` env | Eagle の images ディレクトリ |
| `--log-file` | ✗ | なし | ログ出力先 |
| `--model` | ✗ | `EVA02_Large` | タグ生成モデル名 |
| `--force` | ✗ | false | `.last_run` を無視して全件再処理 |

### 2.2 [`audio_main.py`](../audio_main.py) — 音声タグ生成（PANNs + Whisper）
| 引数 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `--input` / `--input-dir` | ✓ (排他) | - | 単一ファイル または ディレクトリ |
| `--type` | ✗ | 自動判定 | `bgm` / `se` / `voice` 強制指定 |
| `--db-path` | ✗ | なし | 指定時は SQLite にも書き込み |
| `--output-dir` | ✗ | 入力と同じ | JSON 出力先 |
| `--top-k` | ✗ | 20 | 返すタグ最大数 |
| `--no-transcribe` | ✗ | false | Voice の Whisper 文字起こしを無効化 |

### 2.3 [`generate_descriptions.py`](../generate_descriptions.py) — Ollama で説明文生成
`media.desc_text` 列を Ollama で埋める。

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--db-path` | `SQLITE_DB_PATH` env | SQLite DB |
| `--host` | `OLLAMA_DEFAULT_HOST` | Ollama ホスト URL |
| `--model` | `OLLAMA_DEFAULT_MODEL` | Ollama モデル名 |
| `--force` | false | 既存 `desc_text` を上書き |
| `--dry-run` | false | 件数のみ表示 |

### 2.4 [`import_to_sqlite.py`](../import_to_sqlite.py) — JSON → SQLite 直接インポート
images 以下の `tag_palette.json` を CSV マスタで補完して SQLite に書き込む。

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--image-dir` | `EAGLE_IMAGE_DIR` env | Eagle images |
| `--db-path` | `SQLITE_DB_PATH` env | SQLite DB |
| `--dry-run` | false | DB 書き込みしない |
| `--force` | false | 全件再インポート |
| `--since-generated` | なし | `generated_at >= 指定日時` のみ対象 |

### 2.5 サブモジュール直下の `python -m` 互換 CLI
| ファイル | 用途 |
|---|---|
| [`src/tag_palette/novel/ingest_local.py`](../src/tag_palette/novel/ingest_local.py) | Pixiv 小説 .txt / .pdf を SQLite にインジェスト |
| [`src/tag_palette/novel/embedding.py`](../src/tag_palette/novel/embedding.py) | チャンク埋め込み生成 |
| [`src/tag_palette/novel/label_tagger.py`](../src/tag_palette/novel/label_tagger.py) | novel_label と tag を埋め込み類似度で紐付け |
| [`src/tag_palette/novel/translate_chinese.py`](../src/tag_palette/novel/translate_chinese.py) | 中国語 Pixiv 小説の翻訳 |

---

## 3. 生成成果物（ファイルシステム）

Eagle の `images/{id}.info/` ディレクトリ内に書き込まれるファイル群。**eagle backend が読む可能性のあるサイドカーファイル**。

| ファイル | 内容 | スキーマ |
|---|---|---|
| `tag_palette.json` | タグ・センシティブ判定・スコア等の生データ | `MediaPalette` / `AudioPalette` / `NovelPalette` |
| `metadata.json`（Eagle 側既存） | `annotation` と `tags` を上書き | Eagle 仕様 |
| `embedding.npy` | タグ埋め込みベクトル (float32) | sentence-transformers 出力 |
| `ccip_embedding.npy` | キャラクター特徴ベクトル (float32) | imgutils CCIP |
| `pose_embedding.npy` | ポーズ埋め込み (float32) | OpenPose 由来カスタム実装 |
| `{stem}_thumbnail.png` | サムネイル | 200px PIL / ffmpeg |

**書き込み箇所:**
- 画像: [media/tag_writer.py](../src/tag_palette/media/tag_writer.py) `write_tags_to_eagle()`
- 漫画: [manga/tag_writer.py](../src/tag_palette/manga/tag_writer.py) `write_manga_to_eagle()`
- 音声: [audio/tag_writer.py](../src/tag_palette/audio/tag_writer.py) `write_audio_tags_to_eagle()`
- 小説: [novel/tag_writer.py](../src/tag_palette/novel/tag_writer.py) `write_novel_to_eagle()`

---

## 4. 外部リソース

### 4.1 環境変数
[shared/env_config.py](../src/tag_palette/shared/env_config.py) で集約取得（`.env` から `python-dotenv` 経由）。

| 変数 | 用途 | デフォルト |
|---|---|---|
| `EAGLE_IMAGE_DIR` | Eagle ライブラリの images パス | なし（必須） |
| `SQLITE_DB_PATH` | SQLite DB ファイルパス（eagle backend と共有） | なし（必須） |
| `EAGLE_API_URL` | Eagle API URL | `http://localhost:8000` |
| `OLLAMA_HOSTS` | Ollama ホスト群（カンマ区切り） | `OLLAMA_HOST` 経由 → `localhost:11434` |
| `OLLAMA_HOST` | Ollama 単一ホスト（後方互換） | - |
| `HF_HUB_OFFLINE` | HuggingFace Hub オフライン | パッケージ import 時に `1` 強制（既存値あれば尊重） |
| `NOVELS_DIR` | 小説テキストの読み込み元 | なし（novel CLI のみ） |

### 4.2 SQLite テーブル書き込み

`INSERT` / `UPDATE` 対象テーブル一覧（grep ベース）。**eagle ORM `tenant/db/orm.py` のテーブルと完全に一致**。

| テーブル | 書き込み元 | 操作 |
|---|---|---|
| `categories` | importer/media_importer.py | INSERT |
| `genres` | importer/media_importer.py | INSERT |
| `tags` | importer/media_importer.py | INSERT |
| `tag_genres` | importer/media_importer.py | INSERT |
| `tag_embeddings` | importer/media_importer.py | INSERT |
| `media` | importer/media_importer.py, importer/desc_backfill.py | INSERT / UPDATE |
| `media_tags` | importer/media_importer.py | INSERT |
| `media_embeddings` | importer/media_importer.py, importer/desc_backfill.py | INSERT / UPDATE |
| `audio_assets` | importer/audio_importer.py, audio_main.py | INSERT / UPDATE |
| `novels` | importer/novel_importer.py, novel/ingest_local.py | INSERT |
| `novel_series` | novel/ingest_local.py | INSERT |
| `novel_labels` | importer/novel_importer.py, novel/ingest_local.py | INSERT |
| `novel_label_tags` | novel/label_tagger.py | INSERT / DELETE |
| `novel_chunks` | importer/novel_importer.py, novel/ingest_local.py | INSERT |
| `novel_morphemes` | importer/novel_importer.py, novel/ingest_local.py | INSERT |
| `novel_chunk_morphemes` | importer/novel_importer.py, novel/ingest_local.py | INSERT |

⚠ すべて生 SQL（sqlite3 driver 直叩き）。eagle 側の SQLAlchemy ORM とは一切連携していない。

### 4.3 パッケージ同梱データ
[`src/tag_palette/data/`](../src/tag_palette/data/)

| ファイル | 用途 |
|---|---|
| `danbooru_tags.csv` | タグ → カテゴリ・ジャンル・日本語訳の一次マスタ |
| `category.csv` | カテゴリマスタ |
| `genre.csv` | ジャンル日本語名 |
| `tag_category_rules.csv` | パターンベースのカテゴリ判定ルール |
| `translation_cache.csv` | 翻訳キャッシュ（永続） |
| `tag_embeddings.npy` | タグ埋め込みキャッシュ |

### 4.4 状態ファイル
| パス | 内容 | 書き込み元 |
|---|---|---|
| `{image_dir}/.last_run` | `main.py` の前回実行時刻 | shared/run_state.py |
| `{image_dir}/.last_import` | `import_to_sqlite.py` の前回実行時刻 | importer/reader.py |

---

## 5. 重い依存関係（統合時のコスト要因）

[pyproject.toml](../pyproject.toml) より、**eagle backend に持ち込んだ際に問題になりそうな依存**を抽出。

| 依存 | サイズ感 | 主な用途 | 分離可能性 |
|---|---|---|---|
| `torch` | 大（GPU 版で数 GB） | sentence-transformers | sentence-transformers 経由、別ワーカー化容易 |
| `onnxruntime-gpu` | 大 | imgutils タグ生成 | GPU ワーカー必須 |
| `dghs-imgutils` | 中 | WD14/Camie/CCIP/分類スコア | タグ生成パイプの中核 |
| `rembg[gpu]` | 中 | 背景除去（CCIP 前処理？） | 利用箇所要確認 |
| `sentence-transformers` | 中 | チャンク・タグ埋め込み | API/バッチ問わず必要 |
| `ndlocr-lite` | 中（独自リポジトリ） | 漫画 OCR | 別 .git。submodule 化検討 |
| `fugashi` + `unidic-lite` | 中 | 小説形態素解析 | 軽量、API へ持ち込み可 |
| `pdfplumber` | 小 | 小説 PDF パース | 軽量 |
| `googletrans` | 小 | タグ翻訳補完 | ネット必須、optional |
| `ollama` | 小（クライアント） | desc 生成 | 外部サービス、optional |

`schemas.py` は意図的にこれらを一切 import していない（[schemas.py:4](../src/tag_palette/schemas.py#L4) 参照）。**スキーマだけを別パッケージに切り出す前提が既にある**ことが読み取れる。

---

## 6. 統合検討時に効く観察

このインベントリから読み取れる事実をメモ：

1. **DB スキーマは既に eagle 側と完全一致**（テーブル名・カラム名）。tag_palette は生 SQL を、eagle は ORM を使い、同じテーブルに別経路で書いている。→ DB アクセスを ORM 経由に統一するのは比較的小さな差分で可能。
2. **`schemas.py` は意図的に重い依存を排除済み**。共有 Pydantic パッケージとして切り出す下準備ができている。
3. **GPU 必須の処理（タグ生成・CCIP・rembg）と純粋ロジック（schemas / categorize / sensitive 判定 / morpheme 解析）が混在**。前者を別ワーカー、後者を backend 直接取り込み、という分離が自然。
4. **CLI 4 本（`main.py` / `audio_main.py` / `generate_descriptions.py` / `import_to_sqlite.py`）は `tag_palette.json` を中継したパイプラインを構成**。生成 → import の 2 段階。中継ファイルを廃して直接 ORM 書き込みにするか、中継仕様を保つか、が設計争点。
5. **環境変数が eagle と暗黙に共有**（`SQLITE_DB_PATH` / `EAGLE_IMAGE_DIR`）。統合後は eagle の `tenant/config.py` 配下に集約可能。
