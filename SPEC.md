# main.py 仕様書

Eagle ライブラリのコンテンツに対してタグを自動生成し、メタデータに書き戻すバッチ処理スクリプト。

## コマンド

```bash
uv run python main.py --image-dir /path/to/eagle.library/images
uv run python main.py --image-dir /path/to/eagle.library/images --model wd-eva02-large-tagger-v3
uv run python main.py --image-dir /path/to/eagle.library/images --force
uv run python main.py --image-dir /path/to/eagle.library/images --log-file output.log
```

### 引数

| 引数 | 必須 | デフォルト | 説明 |
|------|------|-----------|------|
| `--image-dir` | Yes | - | Eagle ライブラリの `images` ディレクトリ |
| `--model` | No | `wd-eva02-large-tagger-v3` | タグ生成モデル名 |
| `--force` | No | `false` | 既処理スキップを無効化し全件再処理 |
| `--log-file` | No | なし | ログ出力先ファイル (stdout と併用) |

## 対応ファイル形式

### 画像 (PIL でサムネイル生成)

`.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.gif`

### 動画・その他 (ffmpeg でサムネイル生成)

MP4 等の非画像ファイル。Eagle が作成済みのサムネイルがあればそれを使用し、なければ ffmpeg で先頭フレームを抽出してサムネイルを生成する。

## 処理フロー

```
1. 前回実行時刻を読み込み (.last_run)
2. 翻訳キャッシュ・埋め込みキャッシュを読み込み
3. Eagle images ディレクトリを走査し、対象コンテンツを収集
4. 各コンテンツに対して:
   a. サムネイルがなければ生成 (画像: PIL / 動画: ffmpeg)
   b. サムネイルが存在しなければスキップ
   c. サムネイル画像でタグ生成 (WD14 Tagger)
   d. タグの日本語翻訳を取得
   e. Eagle の metadata.json に annotation を書き込み
   f. tag_palette.json にタグ生データを保存
   g. 100件ごとにキャッシュを中間保存
5. キャッシュを最終保存
6. 実行時刻を記録 (.last_run)
```

## 探索フィルタ (find_eagle_images)

以下の条件に該当するコンテンツはスキップされる:

| 条件 | 説明 |
|------|------|
| `isDeleted == true` | Eagle で削除済み |
| `tag_palette.json` が存在 | 既にタグ生成済み (`--force` で無効化) |
| `mtime <= cutoff` | 前回実行以降に更新されていない |
| `name` または `ext` が空 | メタデータ不正 |
| ファイルが存在しない | 実ファイルが見つからない |

## サムネイル生成 (ensure_thumbnail)

| ファイル種別 | 方法 | サイズ |
|-------------|------|--------|
| 画像 | PIL (Lanczos リサイズ → PNG 保存) | 300x300 (アスペクト比維持) |
| 動画・その他 | ffmpeg (先頭フレーム抽出) | 300x300 (アスペクト比維持) |

- サムネイルパス: `{info_dir}/{name}_thumbnail.png`
- 既にサムネイルが存在する場合は何もしない

## タグ生成

- 入力: サムネイル画像 (300x300 PNG)
- モデル: WD14 Tagger (デフォルト: `wd-eva02-large-tagger-v3`)
- 出力: `dict[str, float]` (タグ名 → 信頼度スコア)

## 出力ファイル

### metadata.json (Eagle 標準)

`annotation` フィールドにタグの日本語訳をカンマ区切りで書き込む。

```json
{
  "annotation": "1人の少女, 青い目, 長い髪, ..."
}
```

### tag_palette.json (独自)

各 `{ID}.info/` ディレクトリ内に保存。

```json
{
  "image_id": "XXXXXX",
  "image_name": "photo.jpg",
  "thumbnail_name": "photo_thumbnail.png",
  "ext": "jpg",
  "model_name": "wd-eva02-large-tagger-v3",
  "tags": {
    "1girl": 0.95,
    "blue_eyes": 0.88
  },
  "tags_ja": {
    "1girl": "1人の少女",
    "blue_eyes": "青い目"
  },
  "embedding": "<base64エンコードされた埋め込みベクトル>",
  "generated_at": "2026-03-03T12:00:00.000000"
}
```

## クラッシュ耐性

大量処理 (数万件規模) を想定した耐障害設計:

| 機能 | 説明 |
|------|------|
| 既処理スキップ | `tag_palette.json` が存在するコンテンツはスキップ。クラッシュ後の再実行で二重処理を回避 |
| 定期キャッシュ保存 | 100件ごとに翻訳キャッシュ・埋め込みキャッシュをディスクに保存 (`SAVE_INTERVAL = 100`) |

## 状態管理

| ファイル | 場所 | 内容 |
|---------|------|------|
| `.last_run` | `eagle.library/` 直下 | 前回実行時刻 (ISO 8601) |
| `translation_cache.csv` | パッケージ data ディレクトリ | タグ日本語翻訳キャッシュ |
| `tag_embeddings.npy` | パッケージ data ディレクトリ | タグ埋め込みベクトルキャッシュ |

## 外部依存

| ツール | 必須 | 用途 |
|--------|------|------|
| Python 3.10+ | Yes | ランタイム |
| tag_palette パッケージ | Yes | タグ生成・翻訳・埋め込み |
| PIL (Pillow) | Yes | 画像サムネイル生成 |
| ffmpeg | No | 動画サムネイル生成 (未インストール時は動画スキップ) |
