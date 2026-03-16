# 小説取り込み機能 (Novel Ingestion)

小説テキストをチャンク単位で取り込み、形態素解析・embedding 生成まで行い SQLite に格納するパイプラインです。

---

## 処理パイプライン

```
■ .txt（Pixiv / Fanbox）          ■ .pdf（なろう）               ■ .pdf（独自形式）
  ↓ メタデータ抽出                   ↓ メタデータ抽出（2P目）        ↓ CID 文字マッピング
  ↓ is_sensitive 判定（タグ）         ↓ is_sensitive 判定（1P目）     ↓ 縦書き句読点変換
  ↓ 1 file = 1 novel               ↓ URL 抽出（最終ページ）        ↓ 章分割（W6 Bold 検出）
  │                                 ↓ 章分割（Bold テキスト検出）    ↓ 1 PDF = 1 series + N novels
  │                                 ↓ 1 PDF = 1 series + N novels  │
  └──────────┬──────────────────────┴──────────────────────────────┘
             ↓ 全角英数字 → 半角変換
             ↓ テキストチャンキング（台詞 / 心の声 / 地の文）
             ↓ 形態素解析（名詞・動詞・形容詞を抽出）
             ↓ DB保存（novels, novel_chunks, novel_morphemes 等）
             ↓ embedding 生成（別コマンドで実行）
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

1つの PDF を **1 series + N novels（章単位）** として登録する。

| ページ | 内容 | 抽出データ |
|---|---|---|
| 1ページ | 表紙 | `is_sensitive` 判定（R18/18禁検出） |
| 2ページ | メタデータ（縦書き） | 【小説タイトル】【Ｎコード】【作者名】【あらすじ】 |
| 3ページ〜 | 本文（縦書き） | 章ごとに分割 → 各章が 1 novel |
| 最終ページ | 奥付 | `novels.url`（小説家になろうの作品URL） |

#### 章の検出

- 各ページの最右列（縦書き先頭列）が **太字（MS-Mincho,Bold）** で始まる場合、章の開始と判定
- 最初の章タイトルが見つかるまでのページ（表紙・あらすじ・注意書き等）は自動でスキップ
- 章タイトルはそのまま `novels.title` に設定する（`※` 等の記号も保持）

#### 縦書きレイアウトの改行処理

PDF の縦書きテキストは1列あたり約30文字で折り返されるため、レイアウト上の改行と本当の段落区切りを区別する。

| 列の文字数 | 判定 |
|---|---|
| 29文字以上 | レイアウト折り返し → 改行なしで次の列と結合 |
| 28文字以下 | 本当の段落区切り → 改行を挿入 |

#### ID 体系

| レコード | id | 例 |
|---|---|---|
| novel_series | `{n_code}` | `N5833EQ` |
| novels（各章） | `{n_code}_{seq}` | `N5833EQ_1`, `N5833EQ_2` |

#### novels カラムの設定

| カラム | 値 |
|---|---|
| `series_id` | シリーズ ID（= Nコード） |
| `series_seq` | 章の順番（1-based） |
| `author` | シリーズ共通（メタデータページから取得） |
| `url` | シリーズ共通（最終ページから取得） |
| `is_sensitive` | シリーズ共通（表紙から判定） |

### 独自形式 PDF（`ingest_novels5.py`）

なろう以外の独自フォーマットの縦書き PDF を取り込む専用スクリプト。

#### 特徴

- メタデータページなし（1ページ目から本文開始）
- フォント: HiraginoSans（W6=章タイトル、W3=本文）
- 縦書き句読点（`︑→、` `︒→。` `﹁→「` `﹂→」` 等）を横書きに変換
- **CID 文字マッピング**: フォントの ToUnicode CMap が欠落している文字を手動マッピングで復元
  - 未マッピングの CID が検出された場合は `UnmappedCIDError` 例外を送出して停止する
  - `_CID_MAP` にマッピングを追加してから再実行する

#### 章の検出

- HiraginoSans-W6（太字）フォントの文字列を章タイトルとして検出

#### ID 体系

| レコード | id | 例 |
|---|---|---|
| novel_series | `sha256(ファイル名)[:32]` | `7a3f8b2c...` |
| novels（各章） | `{series_id}_{seq}` | `7a3f8b2c..._1` |

#### novels カラムの設定

- `author`, `url`, `is_sensitive` はスクリプト内で直接指定（PDF にメタデータがないため）

---

## is_sensitive 判定

取り込み時にセンシティブコンテンツを自動判定し、`novels.is_sensitive` に設定する。

| 媒体 | 判定対象 | 判定条件 |
|---|---|---|
| Pixiv (.txt) | タグ（7行目） | `18禁`、`R-18`、`R18` のいずれかがタグに含まれる |
| Fanbox (.txt) | タグ（7行目） | 同上 |
| なろう (.pdf) | 表紙（1ページ目） | テキストに `18禁`、`R-18`、`R18`（全角含む）が含まれる |
| 独自形式 (.pdf) | — | スクリプト内で直接指定 |

---

## 全角→半角変換

すべての媒体で、タイトル登録時に全角英数字を半角に変換する。

- `Ａ-Ｚ` → `A-Z`、`ａ-ｚ` → `a-z`、`０-９` → `0-9`

---

## 冪等性

すべての取り込みスクリプトは冪等に設計されており、同じデータを複数回実行しても安全。

| 媒体 | スキップ判定 |
|---|---|
| Pixiv / Fanbox (.txt) | `novels.id` の存在チェック |
| なろう (.pdf) | `novel_series.id` + 各章の `novels.id` の存在チェック |
| 独自形式 (.pdf) | `novel_series.id`（SHA256） + 各章の `novels.id` の存在チェック |

- 既に登録済みのレコードは更新せずスキップ
- 途中で失敗した場合、未登録の章のみ再取り込みされる

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
- **生成**: 取り込みとは別コマンドで実行（バッチ処理、1024件ずつコミット）

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
| novel_series | シリーズ（PDF 単位） | 1 |
| novels | 作品（txt: 1ファイル=1作品、pdf: 1章=1作品） | 1 |
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
novel_series
└── 1:N ── novels (series_id, series_seq)
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
| `ingest_local.py` | Pixiv/Fanbox (.txt) + なろう (.pdf) の取り込み CLI |
| `ingest_novels5.py` | 独自形式 PDF の取り込み CLI（CID マッピング・縦書き句読点変換） |
| `chunker.py` | テキスト分割（台詞/心の声/地の文 + 地の文再分割） |
| `morpheme.py` | 形態素解析（MeCab / fugashi） |
| `embedding.py` | embedding 生成・保存・コサイン類似検索 CLI |
| `pdf_parser.py` | なろう PDF 縦書きテキスト抽出・章分割（pdfplumber） |
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

### Pixiv / Fanbox / なろう取り込み

```bash
# 通常実行（.env のパスを使用）
uv run python src/tag_palette/novel/ingest_local.py

# ドライラン（ファイル一覧のみ表示）
uv run python src/tag_palette/novel/ingest_local.py --dry-run

# カスタムパス指定
uv run python src/tag_palette/novel/ingest_local.py /path/to/novels --db /path/to/local.db
```

### 独自形式 PDF 取り込み

```bash
# ディレクトリ内の PDF を取り込み
uv run python src/tag_palette/novel/ingest_novels5.py /path/to/pdfs --db /path/to/local.db

# ドライラン
uv run python src/tag_palette/novel/ingest_novels5.py /path/to/pdfs --dry-run
```

### Embedding 生成

```bash
# 全未生成チャンクを処理
uv run python -m tag_palette.novel.embedding --db /path/to/local.db

# 特定の novel_id のみ
uv run python -m tag_palette.novel.embedding --db /path/to/local.db --novel-id <id>

# バッチサイズ指定
uv run python -m tag_palette.novel.embedding --db /path/to/local.db --batch-size 512
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
