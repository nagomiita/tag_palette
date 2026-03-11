# 小説テキスト → 粗チャンク → 形態素解析 → 日本語タグ抽出 → SQLite格納 基盤仕様

## 目的

小説テキストを、まずは雑なチャンク単位で取り込み、各チャンクに含まれる日本語タグ候補を抽出して SQLite に保存する。

この段階では、まだ danbooru タグへの完全な変換や画像検索までは行わず、まずは以下の土台を作る。

- 作品を保存する
- 作品を複数チャンクとして保存する
- 各チャンクから形態素解析でタグ候補を抽出する
- 抽出した日本語タグを辞書化する
- チャンクとタグの対応を保存する

将来的にはこの基盤の上に以下を追加する前提とする。

- 日本語タグ → danbooru タグ候補マッピング
- RapidFuzz によるあいまい一致
- embedding による意味近傍候補
- シーン統合
- 画像検索
- 再ランキング

---

## DB設計

### テーブル一覧

| テーブル | 役割 | 関係 | Phase |
|---|---|---|---|
| **novels** | 作品 | — | 1 |
| **tags** | タグマスタ（取得元サイトで付与されたタグ） | — | 1 |
| **novel_tags** | 作品とタグの紐付け（中間テーブル） | novels ↔ tags (N:N) | 1 |
| **novel_chunks** | チャンク（会話/心の声/地の文を種別ごとに分割） | novels → 1:N | 1 |
| **novel_morphemes** | 形態素辞書（形態素解析で抽出した候補のマスタ） | — | 1 |
| **novel_chunk_morphemes** | チャンクと形態素の紐付け（中間テーブル） | novel_chunks ↔ novel_morphemes (N:N) | 1 |
| **chunk_embeddings** | チャンクの embedding ベクトル | novel_chunks → 1:1 | 2 |
| **routes** | 分岐ルート定義 | novels → 1:N | 2 |
| **route_chunks** | 分岐ルート内のチャンク | routes → 1:N | 2 |

### カラム定義

#### novels

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER PK | ファイル名の `_` より前の数値（外部ID） |
| title | TEXT NOT NULL | ファイル名の `_` より後（拡張子除く） |
| author | TEXT | テキスト3行目 |
| url | TEXT | テキスト1行目 |
| description | TEXT | 説明 |
| created_at | TEXT | 登録日時 |

#### tags

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER PK | 自動採番 |
| name | TEXT NOT NULL UNIQUE | タグ文字列 |

#### novel_tags

| カラム | 型 | 説明 |
|---|---|---|
| novel_id | INTEGER FK | novels.id |
| tag_id | INTEGER FK | tags.id |
| PK | (novel_id, tag_id) | 複合主キー |

#### novel_chunks

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER PK | 自動採番 |
| novel_id | INTEGER FK | novels.id |
| seq | INTEGER | チャンクの順番 |
| kind | TEXT NOT NULL | 種別（"dialogue" / "thought" / "narrative"） |
| body | TEXT NOT NULL | チャンク本文 |

#### novel_morphemes

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER PK | 自動採番 |
| surface | TEXT NOT NULL | 表層形（原文のまま） |
| pos | TEXT NOT NULL | 品詞（名詞・動詞・形容詞） |
| UNIQUE | (surface, pos) | 同一表層形でも品詞違いは別レコード |

#### novel_chunk_morphemes

| カラム | 型 | 説明 |
|---|---|---|
| chunk_id | INTEGER FK | novel_chunks.id |
| morpheme_id | INTEGER FK | novel_morphemes.id |
| count | INTEGER DEFAULT 1 | チャンク内の出現回数 |
| PK | (chunk_id, morpheme_id) | 複合主キー |

### ER図（概要）

```
novels
├── N:N ── novel_tags ── N:N ── tags
├── 1:N ── novel_chunks
│               ├── N:N ── novel_chunk_morphemes ── N:N ── novel_morphemes
│               ├── 1:1 ── chunk_embeddings
│               ├── (fork_from) ←── routes
│               └── (merge_to)  ←── routes
└── 1:N ── routes
                └── 1:N ── route_chunks
```

---

## チャンク分割仕様

### 分割方針

テキストを以下の手順でチャンクに分割する。

#### Step 1: 種別ごとの切り出し

テキストを先頭から走査し、以下のルールで種別ごとに切り出す。

| 種別 | kind | 判定ルール |
|---|---|---|
| 台詞 | dialogue | 「」で囲まれた部分 |
| 心の声 | thought | () または（）で囲まれた部分 |
| 地の文 | narrative | 上記以外 |

台詞・心の声は出現ごとに独立したチャンクとする。

#### Step 2: 地の文の分割

地の文が長い場合、以下のルールでさらに分割する。

| 項目 | 値 |
|---|---|
| 最小チャンクサイズ | 500文字 |
| 最大チャンクサイズ | 1000文字 |
| 分割タイミング | 500文字を超えた後、次のセパレータで切る |
| セパレータ | 改行（`\n`）、句点（。！？） |
| 1000文字到達時 | 次のセパレータで切る |

#### Step 3: seq の付与

切り出した順に seq（通し番号）を振り、原文での出現順序を保持する。

---

## 形態素解析仕様

### ライブラリ

- **MeCab**（Python バインディング: fugashi）
- **辞書**: unidic-lite

### インストール

```bash
uv add fugashi unidic-lite
```

### 抽出対象の品詞

| 品詞 | 対象 |
|---|---|
| 名詞 | 全般 |
| 動詞 | 全般 |
| 形容詞 | 全般 |

上記以外の品詞（助詞、助動詞、接続詞、記号等）は除外する。

### 除外ルール（ストップワード）

#### ひらがな1文字の除外

ひらがなのみで構成された1文字の形態素は除外する（例: 「で」「き」等の動詞活用断片）。
漢字・カタカナ1文字（例: 「剣」「血」）は除外しない。

#### ストップワードリスト

以下の汎用語はタグ候補として意味が薄いため除外する。

| 分類 | 語 |
|---|---|
| 汎用動詞 | する、いる、ある、なる、できる、くる、いく、おる、くれる、もらう、あげる、やる、つく、なす、おく、みる、しまう、しれる、れる、られる、せる、させる |
| 汎用形容詞 | ない、よい、いい |
| 形式名詞・代名詞 | こと、もの、ところ、とき、ため、ほう、よう、それ、これ、あれ、どれ、の、ん |

### 保存形式

- `surface`: 表層形（原文のまま）
- `pos`: 品詞（名詞 / 動詞 / 形容詞）

---

## 入力ファイル仕様

### ファイル形式

テキストファイル（`.txt`）。ファイル名の形式: `{id}_{タイトル}.txt`

### ファイル構造

| 行 | 内容 | 対応カラム |
|---|---|---|
| 1行目 | URL | novels.url |
| 2行目 | 空行 | — |
| 3行目 | 作者名 | novels.author |
| 4行目 | 空行 | — |
| 5行目 | タイトル | novels.title |
| 6行目 | 空行 | — |
| 7行目 | `Tags: タグ1, タグ2, ...` | tags + novel_tags |
| 8行目 | 空行 | — |
| 9行目〜 | 本文 | novel_chunks |

### テスト用入力データ

```
C:\Users\taket\Downloads\novel_test\
├── 20259818_ホムンクルスなりきり体験.txt
└── 21985223_ホムンクルス乳－夢見る家畜－.txt
```

---

## ディレクトリ構成

```
src/tag_palette/
└── novel/
    ├── __init__.py
    ├── db.py                 # SQLite初期化・テーブル作成・CRUD
    ├── chunker.py            # チャンク分割（種別切り出し + 地の文分割）
    ├── morpheme.py           # 形態素解析（MeCab）・抽出・保存
    └── ingest.py             # 統合処理のエントリポイント

tests/
└── test_novel/
    ├── __init__.py
    ├── test_db.py
    ├── test_chunker.py
    └── test_morpheme.py

data/
└── novel_test.db             # テスト用SQLiteファイル（永続化して確認用）
```

### テスト用DB

- テスト実行時に `data/novel_test.db` にDBを作成する
- テストごとに初期化せず、結果を残して手動確認できるようにする

---

## Phase 1 スコープ（完了）

以下は実装済み。

1. SQLite 初期化
2. 作品登録
3. チャンク分割・登録
4. 形態素解析
5. 名詞・動詞・形容詞をタグ候補として抽出
6. `novel_morphemes` テーブルへ保存
7. `novel_chunk_morphemes` テーブルへ保存
8. CLI による一括取り込み

---

## Phase 2: チャンク embedding + 分岐ルート構造

### 目的

1. **チャンク embedding**: 各チャンクのベクトル表現を保存し、類似シーン検索を可能にする
2. **分岐ルート構造**: ノベルゲームのような分岐・合流を表現し、ユーザーが「ここはこうしたい」と思ったシーンに対して if ルートを作成できるようにする

---

### 2-1. チャンク embedding

#### 概要

各チャンクの本文から embedding ベクトルを生成し、コサイン類似度で類似シーンを検索できるようにする。

#### テーブル: chunk_embeddings

| カラム | 型 | 説明 |
|---|---|---|
| chunk_id | INTEGER PK FK | novel_chunks.id（1:1） |
| embedding | BLOB NOT NULL | embedding ベクトル（numpy float32 の bytes） |
| model | TEXT NOT NULL | 使用モデル名（例: "text-embedding-3-small"） |
| created_at | TEXT | 生成日時 |

#### 仕様

- embedding は numpy float32 配列を `.tobytes()` で BLOB として保存
- 読み出し時は `np.frombuffer(blob, dtype=np.float32)` で復元
- 類似検索はアプリケーション側で全チャンクをロードしコサイン類似度を計算（SQLite 内では行わない）
- モデルは差し替え可能にするため `model` カラムで管理

#### 類似検索の流れ

1. 対象チャンクの embedding を取得
2. 全チャンク（または同一作品内）の embedding をロード
3. コサイン類似度を計算
4. 上位 N 件を返す

---

### 2-2. 分岐ルート構造

#### 概要

ノベルゲームの分岐構造を参考に、既存のチャンク列（正規ルート）から分岐して独自のチャンク列を作成できる。分岐後は元のルートに合流するか、独立したまま終了するかを選べる。

#### 設計方針

ノベルゲームで一般的な**ノードグラフ＋ルート管理**のハイブリッド方式を採用する。

- **ルート（routes）**: 分岐の単位。名前と説明を持つ
- **分岐点（fork）**: 正規ルートのどのチャンクから分岐するか
- **合流点（merge）**: 分岐先のチャンクが正規ルートのどこに戻るか（NULL なら独立終了）
- 正規ルートは暗黙的に存在し、`novel_chunks` の seq 順がそのまま正規ルート

#### テーブル: routes

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER PK | 自動採番 |
| novel_id | INTEGER FK | novels.id |
| name | TEXT NOT NULL | ルート名（例: "if: 戦闘回避ルート"） |
| description | TEXT | ルートの説明 |
| fork_from_chunk_id | INTEGER FK | 分岐元の novel_chunks.id（この直後から分岐） |
| merge_to_chunk_id | INTEGER FK NULL | 合流先の novel_chunks.id（NULL = 独立終了） |
| created_at | TEXT | 作成日時 |

#### テーブル: route_chunks

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER PK | 自動採番 |
| route_id | INTEGER FK | routes.id |
| seq | INTEGER NOT NULL | ルート内の順番 |
| kind | TEXT NOT NULL | 種別（"dialogue" / "thought" / "narrative"） |
| body | TEXT NOT NULL | チャンク本文 |

#### ER図（Phase 2 追加分）

```
novels
├── 1:N ── novel_chunks
│               ├── 1:1 ── chunk_embeddings
│               ├── (fork_from) ←── routes
│               └── (merge_to)  ←── routes
└── 1:N ── routes
                └── 1:N ── route_chunks
```

#### 分岐の例

```
正規ルート:  C1 → C2 → C3 → C4 → C5 → C6
                        │                 ↑
                        └─ [if: 戦闘回避] ─┘
                           R1 → R2 → R3
                           (fork_from=C3, merge_to=C6)

正規ルート:  C1 → C2 → C3 → C4 → C5
                        │
                        └─ [if: バッドエンド] → R1 → R2 (END)
                           (fork_from=C3, merge_to=NULL)
```

#### route_chunks と novel_chunks の関係

- `route_chunks` は `novel_chunks` と同じ構造（kind, body）を持つが、独立したテーブル
- 分岐ルートは創作用途のため、形態素解析・embedding は適用しない

---

### Phase 2 ディレクトリ構成（追加分）

```
src/tag_palette/
└── novel/
    ├── embedding.py          # embedding 生成・保存・類似検索
    └── route.py              # 分岐ルート CRUD

tests/
└── test_novel/
    ├── test_embedding.py
    └── test_route.py
```

---

### Phase 2 スコープ

今回実装するもの:

1. `chunk_embeddings` テーブル追加・embedding 保存
2. コサイン類似度による類似チャンク検索
3. `routes` / `route_chunks` テーブル追加
4. ルートの作成・チャンク追加・合流設定

今回やらないもの:

- 自動分岐提案
- ルート間の差分表示
- danbooru タグ変換
- UI / API

---
