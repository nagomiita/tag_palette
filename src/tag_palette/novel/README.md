# 小説取り込み機能 (Novel Ingestion)

小説テキストをチャンク単位で取り込み、形態素解析・embedding 生成まで行い SQLite に格納するパイプラインです。

---

## 処理パイプライン

```
入力ファイル (.txt / .pdf)
  ↓ メタデータ抽出（タイトル、著者、URL、タグ）
  ↓ テキストチャンキング（台詞 / 心の声 / 地の文）
  ↓ 形態素解析（名詞・動詞・形容詞を抽出）
  ↓ DB保存（novels, novel_chunks, novel_morphemes 等）
  ↓ embedding 生成（multilingual-e5-small, 384次元）
  ↓ ルート管理（分岐・合流パス）
```

---

## 入力フォーマット

### Pixiv テキスト (`{pixiv_id}_{タイトル}.txt`)

| 行 | 内容 | 対応カラム |
|---|---|---|
| 1行目 | URL | novels.url |
| 2行目 | 空行 | — |
| 3行目 | 作者名 | novels.author |
| 4行目 | 空行 | — |
| 5行目 | タイトル | novels.title |
| 6行目 | 空行 | — |
| 7行目 | `Tags: ラベル1, ラベル2, ...` | novel_labels + novel_label_associations |
| 8行目 | 空行 | — |
| 9行目〜 | 本文 | novel_chunks |

> **id の決定**: ファイル名の `_` より前の数値を id として使用する。

### なろう PDF (`{n_code}.pdf`)

| ページ | 内容 |
|---|---|
| 1ページ | 表紙 |
| 2ページ | メタデータ（縦書き）: 【作品タイトル】【Ｎコード】【作者名】【あらすじ】 |
| 3ページ〜 | 本文（縦書き） |

---

## チャンク分割仕様

### Step 1: 種別ごとの切り出し

| 種別 | kind | 判定ルール |
|---|---|---|
| 台詞 | dialogue | `「」` で囲まれた部分 |
| 心の声 | thought | `()` または `（）` で囲まれた部分 |
| 地の文 | narrative | 上記以外 |

### Step 2: 地の文の分割

| 項目 | 値 |
|---|---|
| 最小チャンクサイズ | 500文字 |
| 最大チャンクサイズ | 1000文字 |
| 分割タイミング | 500文字を超えた後、次のセパレータで切る |
| セパレータ | 改行（`\n`）、句点（`。！？`） |

### Step 3: seq の付与

切り出した順に seq（通し番号）を振り、原文での出現順序を保持する。

---

## 形態素解析仕様

- **ライブラリ**: MeCab（Python バインディング: fugashi）+ unidic-lite 辞書
- **抽出対象品詞**: 名詞、動詞、形容詞
- **除外ルール**:
  - ひらがなのみ1文字の形態素（漢字・カタカナ1文字は除外しない）
  - ストップワード: 汎用動詞（する、いる、ある、なる等）、汎用形容詞（ない、よい）、形式名詞・代名詞（こと、もの、ところ等）
- **保存形式**: `surface`（表層形）+ `pos`（品詞）

---

## Embedding 仕様

- **モデル**: `intfloat/multilingual-e5-small`（384次元）
- **保存形式**: numpy float32 配列を `.tobytes()` で BLOB 保存
- **類似検索**: アプリケーション側で全チャンクをロードしコサイン類似度を計算

---

## 分岐ルート構造

ノベルゲームの分岐構造を参考に、正規ルート（novel_chunks の seq 順）から分岐して独自のチャンク列を作成できる。

```
正規ルート:  C1 → C2 → C3 → C4 → C5 → C6
                        │                 ↑
                        └─ [if: 戦闘回避] ─┘
                           R1 → R2 → R3
                           (fork_from=C3, merge_to=C6)
```

- **fork**: 正規ルートのどのチャンクから分岐するか
- **merge**: 正規ルートのどこに戻るか（NULL なら独立終了）

---

## DB設計

### テーブル一覧

| テーブル | 役割 | Phase |
|---|---|---|
| novels | 作品 | 1 |
| novel_labels | ラベルマスタ | 1 |
| novel_label_associations | 作品 ↔ ラベル（N:N） | 1 |
| novel_chunks | チャンク（台詞/心の声/地の文） | 1 |
| novel_morphemes | 形態素辞書 | 1 |
| novel_chunk_morphemes | チャンク ↔ 形態素（N:N） | 1 |
| chunk_embeddings | チャンクの embedding ベクトル | 2 |
| routes | 分岐ルート定義 | 2 |
| route_chunks | 分岐ルート内のチャンク | 2 |

> 全テーブルは `id` (VARCHAR(128) PK, UUID自動生成)、`created_at`、`updated_at` を共通カラムとして持つ。

### ER図

```
novels
├── N:N ── novel_label_associations ── N:N ── novel_labels
├── 1:N ── novel_chunks
│               ├── N:N ── novel_chunk_morphemes ── N:N ── novel_morphemes
│               ├── 1:1 ── chunk_embeddings
│               ├── (fork_from) ←── routes
│               └── (merge_to)  ←── routes
└── 1:N ── routes
                └── 1:N ── route_chunks
```

---

## モジュール構成

| ファイル | 役割 |
|---|---|
| `ingest_local.py` | CLIエントリポイント・取り込みロジック |
| `chunker.py` | テキスト分割（台詞/心の声/地の文 + 地の文再分割） |
| `morpheme.py` | 形態素解析（MeCab / fugashi） |
| `embedding.py` | embedding 生成・保存・コサイン類似検索 |
| `pdf_parser.py` | PDF 縦書きテキスト抽出（pdfplumber） |
| `route.py` | 分岐ルート CRUD |

---

## 依存パッケージ

`pyproject.toml` で管理。追加・更新は `uv add` を使用する。

| パッケージ | 用途 |
|---|---|
| fugashi >= 1.5.2 | MeCab Python バインディング |
| unidic-lite >= 1.0.8 | MeCab 辞書 |
| sentence-transformers >= 3.0.0 | embedding 生成 |
| pdfplumber | PDF 解析 |
| ollama >= 0.6.1 | シーン描写生成（Ollama LLM） |
| numpy >= 1.26.4 | ベクトル演算 |
| python-dotenv >= 1.2.2 | 環境変数読み込み |

---

## 設定（.env）

```env
SQLITE_DB_PATH=/path/to/local.db    # SQLite データベースパス
NOVELS_DIR=/path/to/novels/          # 小説ファイルディレクトリ
EAGLE_API_URL=http://localhost:8000  # Eagle API エンドポイント
```

---

## セットアップ

```bash
# 依存パッケージのインストール
uv sync
```

## 実行方法

```bash
# 通常実行（.env のパスを使用）
uv run python src/tag_palette/novel/ingest_local.py

# ドライラン（ファイル一覧のみ表示）
uv run python src/tag_palette/novel/ingest_local.py --dry-run

# カスタムパス指定
uv run python src/tag_palette/novel/ingest_local.py /path/to/novels --db /path/to/local.db
```

## テスト

```bash
uv run pytest tests/test_novel/
```

---

## 将来構想

この基盤の上に以下を追加予定:

- 日本語タグ → danbooru タグ候補マッピング
- RapidFuzz によるあいまい一致
- embedding による意味近傍候補
- シーン統合
- 画像検索
- 再ランキング
