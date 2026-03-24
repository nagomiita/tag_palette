# tag-palette

WD14 Tagger を使った画像タグ生成ライブラリ。

タグ生成に加え、日英翻訳、カテゴリ分類、ジャンル抽出、センシティブコンテンツ判定機能を提供します。

## インストール

```bash
pip install -e .
```

## 使い方

### タグ生成

画像からタグを自動生成します。初回実行時に HuggingFace Hub からモデルが自動ダウンロードされます。

```python
from tag_palette import generate_tags

results = generate_tags("path/to/image.jpg")
for result in results:
    print(f"Model: {result.model_name}")
    for tag, confidence in result.tags.items():
        print(f"  {tag}: {confidence:.2f}")
```

デフォルトモデルは `EVA02_Large` です。モデルを指定することもできます。

```python
results = generate_tags("image.jpg", model_name="pixai")
```

全モデルで推論する場合:

```python
results = generate_tags("image.jpg", use_all_models=True)
```

#### 対応モデル一覧

| モデル名 | 種別 |
|---------|------|
| `EVA02_Large` | WD14 (デフォルト) |
| `ViT_Large` | WD14 |
| `SwinV2_v3` | WD14 |
| `ConvNext_v3` | WD14 |
| `ViT_v3` | WD14 |
| `SwinV2` | WD14 |
| `ConvNext` | WD14 |
| `ConvNextV2` | WD14 |
| `ViT` | WD14 |
| `MOAT` | WD14 |
| `camie_initial` | Camie Tagger |
| `camie_v2` | Camie Tagger |
| `mldanbooru` | ML-Danbooru |
| `pixai` | PixAI |

### タグのカテゴリ分類

Danbooru のカテゴリ体系に基づいてタグを分類します。

```python
from tag_palette import get_tag_category

get_tag_category("1girl")         # "general"
get_tag_category("hatsune_miku")  # "character"
get_tag_category("vocaloid")      # "copyright"
```

カテゴリ: `general`, `artist`, `copyright`, `character`, `meta`

### センシティブ判定

WD14 の rating からセンシティブコンテンツに該当するか判定します。

```python
from tag_palette import generate_tags, is_sensitive_by_ratings

result = generate_tags("image.jpg")[0]
is_sensitive_by_ratings(result.ratings)  # True / False / None
```

### タグの日本語翻訳

CSV の alias 情報からタグの日本語翻訳を取得します。

```python
from tag_palette import get_translation_for_tag

result = get_translation_for_tag("hatsune_miku")
if result:
    translated_name, note = result
    print(translated_name)  # "初音ミク"
```

Google 翻訳 API による翻訳も利用できます (ネットワーク接続が必要):

```python
import asyncio
from tag_palette import text_translate

translated = asyncio.run(text_translate("blue eyes", src="en", dest="ja"))
print(translated)  # "青い目"
```

### ジャンル抽出

タグ名の括弧からジャンル (作品名等) を抽出し、日本語訳を付与します。

```python
from tag_palette import get_genres

genres = get_genres("artoria_pendragon_(fate)")
# [("fate", "フェイト", "Fate, フェイト, ...")]
```

### 組み合わせ例

```python
from tag_palette import (
    generate_tags,
    get_tag_category,
    get_translation_for_tag,
    is_sensitive_by_ratings,
)

results = generate_tags("image.jpg")
for result in results:
    for tag, confidence in result.tags.items():
        category = get_tag_category(tag)
        sensitive = is_sensitive_by_ratings(result.ratings)
        translation = get_translation_for_tag(tag)
        ja_name = translation[0] if translation else tag

        print(f"{tag} ({ja_name}) [{category}] {confidence:.2f}", end="")
        if sensitive:
            print(" [SENSITIVE]", end="")
        print()
```

## 環境設定

`.env` ファイルでパスを設定します。

```env
SQLITE_DB_PATH=C:\Users\taket\my_project\eagle\backend\local.db
NOVELS_DIR=C:\Users\taket\Pictures\icloud.library\novels
```

## バッチスクリプト

### main.py — Eagle ライブラリのタグ一括生成

Eagle ライブラリの images ディレクトリを走査し、各コンテンツにタグを自動生成して metadata.json と tag_palette.json に書き戻す。

```bash
# 基本実行 (前回以降の新規コンテンツのみ)
uv run python main.py --image-dir /path/to/eagle.library/images

# モデル指定
uv run python main.py --image-dir /path/to/eagle.library/images --model EVA02_Large

# 全件再処理 (既処理スキップを無効化)
uv run python main.py --image-dir /path/to/eagle.library/images --force

# ログファイル出力
uv run python main.py --image-dir /path/to/eagle.library/images --log-file output.log
```

| 引数 | 必須 | デフォルト | 説明 |
|------|------|-----------|------|
| `--image-dir` | Yes | - | Eagle ライブラリの images ディレクトリ |
| `--model` | No | `EVA02_Large` | タグ生成モデル名 |
| `--force` | No | `false` | 既処理スキップを無効化し全件再処理 |
| `--log-file` | No | なし | ログ出力先ファイル |

画像・GIF はサムネイルを PIL で生成、動画 (MP4 等) は ffmpeg で先頭フレームを抽出してサムネイルを生成し、そのサムネイルでタグ生成を行う。


## 小説テキスト処理 (`tag_palette.novel`)

Pixiv 小説テキストをチャンク分割・形態素解析し、本番 SQLite (`local.db`) に格納する。

### インジェスト

`NOVELS_DIR` に配置された `{pixiv_id}_{title}.txt` ファイルを処理する。

```bash
# .env の NOVELS_DIR / SQLITE_DB_PATH を使用 (dry-run)
python src/tag_palette/novel/ingest_local.py --dry-run

# 実行
python src/tag_palette/novel/ingest_local.py

# ディレクトリ・DB を明示指定
python src/tag_palette/novel/ingest_local.py /path/to/novels --db /path/to/local.db
```

既に DB に存在する novel_id は自動スキップされる。

### モジュール構成

| ファイル | 役割 |
|---------|------|
| `ingest_local.py` | 本番 DB へのインジェスト CLI |
| `chunker.py` | テキストをセリフ・心情・地の文にチャンク分割 |
| `morpheme.py` | MeCab (fugashi) による形態素解析 |
| `embedding.py` | チャンク埋め込みベクトル生成・類似検索 |
| `route.py` | 分岐ルート CRUD |

### DB テーブル (本番 ORM)

| テーブル | 説明 |
|---------|------|
| `novels` | 小説メタデータ (id = Pixiv ID) |
| `novel_labels` | ラベル (旧タグ) |
| `novel_label_associations` | 小説↔ラベル関連 |
| `novel_chunks` | チャンク (dialogue / thought / narrative) |
| `novel_morphemes` | 形態素 (surface + pos) |
| `novel_chunk_morphemes` | チャンク↔形態素 (出現回数) |
| `chunk_embeddings` | チャンク埋め込みベクトル |
| `routes` | 分岐ルート定義 |
| `route_chunks` | ルート内チャンク |

### Windows での実行

パスを Windows 形式にして同様に実行できる。動画サムネイル生成には ffmpeg のインストールが必要。

```powershell
# ffmpeg インストール
winget install ffmpeg

# 実行
uv run python main.py --image-dir "D:\eagle.library\images"
```

## パッケージデータ

`src/tag_palette/data/danbooru_tags.csv` にタグメタデータ CSV を配置してください。カテゴリ分類・翻訳・ジャンル抽出に使用されます。

## 依存ライブラリ

| ライブラリ | 用途 |
|-----------|------|
| `pillow` | 画像読み込み・前処理 |
| `numpy` | 数値演算・画像配列処理 |
| `opencv-python-headless` | 画像リサイズ・パディング |
| `onnxruntime` | ONNX モデル推論 |
| `huggingface-hub` | モデルの自動ダウンロード |
| `pandas` | CSV タグデータ処理 |
| `googletrans` | Google 翻訳 API |
| `python-dotenv` | .env ファイル読み込み |
| `fugashi` + `unidic-lite` | MeCab 形態素解析 |
| `sentence-transformers` | チャンク埋め込みベクトル生成 |

## 開発

```bash
pip install -e ".[dev]"
pytest
```
