# tag-palette

WD14 Tagger を使った画像タグ生成ライブラリ。

タグ生成に加え、日英翻訳、カテゴリ分類、ジャンル抽出、センシティブコンテンツ判定機能を提供します。

## インストール

```bash
pip install -e .
```

> **Note:** `lib/wd14tagger` (WD14 Tagger) を別途セットアップする必要があります。

## 使い方

### タグ生成

```python
from tag_palette import generate_tags

results = generate_tags("path/to/image.jpg")
for result in results:
    print(f"Model: {result.model_name}")
    for tag, confidence in result.tags.items():
        print(f"  {tag}: {confidence:.2f}")
```

### タグのカテゴリ分類

```python
from tag_palette import get_tag_category

category = get_tag_category("1girl")  # "general"
category = get_tag_category("hatsune_miku")  # "character"
```

### センシティブ判定

```python
from tag_palette import is_sensitive

is_sensitive("flower")   # False
is_sensitive("bondage")  # True
```

### タグの日本語翻訳

```python
from tag_palette import get_translation_for_tag

result = get_translation_for_tag("hatsune_miku")
if result:
    translated_name, note = result
    print(translated_name)  # "初音ミク"
```

### ジャンル抽出

```python
from tag_palette import get_genres

genres = get_genres("artoria_pendragon_(fate)")
# [("fate", "Fate", "Fate, ...")]
```

## パッケージデータ

`src/tag_palette/data/danbooru_tags.csv` にタグメタデータ CSV を配置してください。

## 依存ライブラリ

- `pillow` - 画像処理
- `pandas` - CSV データ処理
- `numpy` - 数値演算
- `googletrans` - Google 翻訳 API
- `lib/wd14tagger` - WD14 Tagger (別途セットアップ)
