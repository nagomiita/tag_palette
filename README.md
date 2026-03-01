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

デフォルトモデルは `wd-eva02-large-tagger-v3` です。モデルを指定することもできます。

```python
results = generate_tags("image.jpg", model_name="pixai-tagger-v0.9")
```

全モデルで推論する場合:

```python
results = generate_tags("image.jpg", use_all_models=True)
```

#### 対応モデル一覧

| モデル名 | 種別 |
|---------|------|
| `wd-eva02-large-tagger-v3` | WaifuDiffusion (デフォルト) |
| `wd-vit-large-tagger-v3` | WaifuDiffusion |
| `wd14-convnextv2.v1` | WaifuDiffusion |
| `wd14-vit.v1` / `wd14-vit.v2` | WaifuDiffusion |
| `wd14-convnext.v1` / `wd14-convnext.v2` | WaifuDiffusion |
| `wd14-swinv2-v1` | WaifuDiffusion |
| `wd-v1-4-moat-tagger.v2` | WaifuDiffusion |
| `wd-v1-4-vit-tagger.v3` | WaifuDiffusion |
| `wd-v1-4-convnext-tagger.v3` | WaifuDiffusion |
| `wd-v1-4-swinv2-tagger.v3` | WaifuDiffusion |
| `z3d-e621-convnext-toynya` | WaifuDiffusion |
| `z3d-e621-convnext-silveroxides` | WaifuDiffusion |
| `mld-caformer.dec-5-97527` | ML-Danbooru |
| `mld-tresnetd.6-30000` | ML-Danbooru |
| `camie-tagger` | Camie Tagger |
| `camie-tagger-v2` | Camie Tagger |

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

タグがセンシティブコンテンツに該当するか判定します。

```python
from tag_palette import is_sensitive

is_sensitive("flower")   # False
is_sensitive("bondage")  # True
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
from tag_palette import generate_tags, get_tag_category, is_sensitive, get_translation_for_tag

results = generate_tags("image.jpg")
for result in results:
    for tag, confidence in result.tags.items():
        category = get_tag_category(tag)
        sensitive = is_sensitive(tag)
        translation = get_translation_for_tag(tag)
        ja_name = translation[0] if translation else tag

        print(f"{tag} ({ja_name}) [{category}] {confidence:.2f}", end="")
        if sensitive:
            print(" [SENSITIVE]", end="")
        print()
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

## 開発

```bash
pip install -e ".[dev]"
pytest
```
