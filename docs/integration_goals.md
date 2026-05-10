# tag_palette × eagle 統合ゴール定義

[integration_inventory.md](./integration_inventory.md) と [db_writepoint_map.md](./db_writepoint_map.md) で固めた**現状理解**の上に、**何を達成すれば「統合完了」と呼べるか**を明文化する。後続の ADR（Architecture Decision Record）と移行計画の入力。

策定日: 2026-05-09。
最終決定者: konnichiwatakeshi@gmail.com。

---

## 1. 既知の状態（要約）

詳細は前 2 ドキュメント参照。要点のみ:

- tag_palette は重い ML ライブラリ（torch / onnxruntime-gpu / dghs-imgutils / sentence-transformers / ndlocr-lite / rembg）を持つ Python パッケージ。CLI 4 本＋ライブラリ API。
- eagle backend は FastAPI + SQLAlchemy ORM の Universal モノレポの一部。Python 3.14、`dghs-imgutils` / `onnxruntime-gpu` / `ollama` を**既に依存に持つ**。
- DB は両者で**同じテーブル群**を共有（テーブル名は完全一致）。tag_palette は生 SQL、eagle は ORM。
- **既に動いている統合点が 2 つある:**
  - [`tenant/api/tag_palette_import/endpoint.py`](../../eagle/backend/tenant/api/tag_palette_import/endpoint.py) — HTTP バルクインポート（ORM 経由）
  - [`tenant/api/media_similar/_tagger.py`](../../eagle/backend/tenant/api/media_similar/_tagger.py) — eagle 側に独自実装された **WD14 タガーのコピー**
- 中継ファイル `tag_palette.json` を介した 2 段階パイプライン（生成 → import）が現運用。

---

## 2. 統合動機（なぜ今やるか）

ユーザー確認済み・優先度順。

### G1. WD14 タガーの重複実装を一元化
[`media_similar/_tagger.py`](../../eagle/backend/tenant/api/media_similar/_tagger.py) と [`tag_palette/media/tagger.py`](../src/tag_palette/media/tagger.py) で同じ WD14 推論ロジックが**並存**している。バージョン違い・モデル名の食い違い・除外タグの差分が生じやすく、長期メンテナンスコストが高い。

**ゴール:** タガー実装は 1 箇所のみ。eagle 側はそのインターフェイスを呼ぶだけにする。

### G2. CLI 手動実行をフロントエンドから使えるようにする
現状 `main.py` / `audio_main.py` / `import_to_sqlite.py` を**人間がターミナルで手動実行**。Frontend にボタンが無く、UX が断絶している。

**ゴール:** Frontend のメディア詳細から「タグ再生成」「説明文生成」等を**同期 API 呼び出し**でトリガーできる。

### G3. DB 書き込みを ORM 経由に統一しスキーマ進化に追随
tag_palette が生 SQL、eagle が ORM で同じテーブルへ書く現状は、列追加・enum 拡張・FK 変更のたびに**両側を手で揃える必要**がある。実際に [db_writepoint_map.md](./db_writepoint_map.md) で複数のドリフト（id 欠落、UPDATE 空振り、enum 値表現）が顕在化済み。

**ゴール:** 統合後の DB 書き込みは eagle ORM のみ。tag_palette は ORM への入力データを返す責務に絞る。

### G4. `tag_palette.json` / `metadata.json` サイドカーを廃止し DB 一本化
Eagle ライブラリの `images/{id}.info/` 配下に作る中継ファイルは、生成 → import の 2 段パイプラインの遺物。**真実の所在地が 2 箇所**（DB と JSON）になっており整合性管理コストが大きい。

**ゴール:** 中継 JSON はゼロ。タガー出力は API レスポンスとして直接 ORM に書き込まれる。`metadata.json`（Eagle 側既存）は読み取り専用で扱い、tag_palette からの上書きを止める。

---

## 3. 主要呼び出しシナリオ

ユーザー確認済み: **Frontend からの同期 API 呼び出し**を主軸とする。

### S1（主）: ユーザー操作によるオンデマンド処理
1. ユーザーが Frontend のメディア詳細で「タグ生成」「説明文生成」「センシティブ判定」等のボタン押下
2. Frontend が eagle backend のエンドポイントを叩く（既存 `media_tagger/predict` の枠）
3. eagle backend が GPU ワーカーへ HTTP リクエスト（後述 §4）
4. GPU ワーカーがタガー推論を実行し、結果を返却
5. eagle backend が ORM 経由で DB に書き込み、Frontend にレスポンス

**SLO 目安:** P50 5 秒、P95 30 秒（GPU の推論時間に支配される）。タイムアウトはエンドポイントごとに別途定義。

### S2（副）: 既存の手動 CLI を残置
[`main.py`](../main.py) 等の手動 CLI は**当面は残す**。バルク再処理（モデル切り替え時の全件再推論など）は CLI が現実的。ただし CLI も **eagle ORM への HTTP 呼び出し**にリファクタし、生 SQL を消す方針。

**非ゴール:** Frontend からのバックグラウンドジョブ実行（キュー、スケジューラ連携）は今回のスコープ外。S1 の同期処理が安定してから別フェーズで検討。

---

## 4. デプロイ・実行モデル

ユーザー確認済み: **別マシンに GPU 専用ワーカー、HTTP 経由で呼び出し**（Ollama サーバーと同様の構成）。

```
 ┌────────────┐  HTTP  ┌──────────────┐  HTTP  ┌────────────────┐
 │  Frontend  │───────▶│ eagle backend│───────▶│  GPU Worker    │
 │   (React)  │        │  (FastAPI)   │        │  (tag_palette) │
 └────────────┘        └──────┬───────┘        └────────────────┘
                              │ ORM
                              ▼
                       ┌──────────────┐
                       │   SQLite     │
                       │  (local.db)  │
                       └──────────────┘
```

**役割分担:**

| コンポーネント | 役割 | 持つ重い依存 |
|---|---|---|
| Frontend | UI、ボタン操作 | なし |
| eagle backend | API ゲートウェイ、ORM 書き込み、認可、トランザクション境界 | 軽量（既に持つ `dghs-imgutils` / `onnxruntime-gpu` は**最終的に削除対象**） |
| GPU Worker（新規） | tag_palette を内包し、HTTP で推論 API を公開 | torch / onnxruntime-gpu / dghs-imgutils / ndlocr-lite / sentence-transformers / rembg |
| SQLite | データ永続化 | なし |

**ネットワーク前提:**
- GPU Worker は LAN 内に存在（Ollama サーバーと同じネットワーク帯）
- 認証は最低限（API トークン or LAN 内信頼）。本番公開を想定しない
- Eagle ライブラリの `images/` ディレクトリは **eagle backend と GPU Worker の双方からアクセス可能**（共有ストレージ or NAS マウント）

**境界判断のポイント:**
- 推論結果（タグ・スコア・埋め込みベクトル）は GPU Worker から JSON で返り、**eagle backend が ORM 経由で書く**。GPU Worker は DB に直接触らない
- 大きなバイナリ（埋め込み `.npy`）は base64 エンコードで HTTP に乗せる（既存 [tag_palette_import](../../eagle/backend/tenant/api/tag_palette_import/endpoint.py) と同じスタイル）

---

## 5. 非機能要件

| 項目 | 要件 | 根拠 |
|---|---|---|
| **応答時間（同期 API）** | タグ生成 P95 < 30s、説明文生成 P95 < 60s | GPU 推論 + Ollama LLM 待ちの実測想定 |
| **同時実行** | GPU Worker は逐次処理可で十分（ロックで直列化）。eagle backend は I/O 待ちなので並行可 | 単一ユーザー想定 |
| **可用性** | GPU Worker 停止時は eagle backend が **5xx を返す**（degrade せず明示的に失敗） | 個人運用なので人間が再起動する前提 |
| **整合性** | DB 書き込みは eagle backend の単一トランザクション境界に限定 | ORM 一本化の前提 |
| **モデル管理** | モデル更新は GPU Worker のデプロイ単位で完結。eagle backend はモデル名の文字列だけ知る | デカップリング |
| **GPU メモリ** | 同時に動く ML モデルは制御。タガー × Ollama × rembg の同時ロードは避ける | OOM 回避 |
| **ロギング** | eagle backend のリクエストログに GPU Worker への呼び出しと所要時間を残す | 障害解析・SLO 監視 |
| **後方互換** | tag_palette CLI は移行期間中は動き続ける | 既存ライブラリの一括再処理を止めない |

---

## 6. スコープ境界

### 6.1 In Scope（今回の統合で完了させる）
- WD14 タガーを GPU Worker 側に集約。`media_similar/_tagger.py` を**廃止 or 薄いクライアント**に置換
- Frontend の同期 API 呼び出し経路を整備（既存 `media_tagger/predict` 拡張）
- tag_palette CLI の DB 書き込みを**全て** eagle backend HTTP API 経由に置換
- `tag_palette.json` / `metadata.json` への書き込みを**廃止**
- `schemas.py` を共有 Pydantic パッケージとして分離（既に重い依存を排除済み）
- 二重実装の解消: 小説（novel_importer/ingest_local）、音声（audio_importer/audio_main）

### 6.2 Out of Scope（今回はやらない）
- バックグラウンドジョブキュー（Celery / RQ / arq）の導入
- マルチテナント対応
- GPU Worker の冗長化・水平スケール
- Frontend の UI 大幅刷新（既存ボタン枠の再利用に留める）
- DB エンジン移行（SQLite → PostgreSQL）。ただし**移行を妨げない設計**は保つ
- `tag_palette` リポジトリの完全凍結。少なくとも GPU Worker のソースとして生き続ける

### 6.3 Will Be Decided in ADR（次フェーズ）
| 論点 | 選択肢 |
|---|---|
| GPU Worker のフレームワーク | FastAPI / Litestar / 軽量 Flask / gRPC |
| `schemas.py` の所在 | 別 PyPI パッケージ / git submodule / monorepo 化 |
| 既存 Eagle ライブラリ `images/{id}.info/tag_palette.json` の扱い | 廃止と削除タイミング、移行期間中の読み込みフォールバック |
| `chunk_embeddings` の DB 書き込みを誰がやるか | GPU Worker / eagle backend / 別バッチ |
| 認証方式 | API トークン / LAN 内信頼 / mTLS |

---

## 7. 成功基準

統合完了の判定基準:

1. **重複ゼロ**: WD14 タガーのコードが**ただ 1 箇所**に存在する（grep しても重複しない）
2. **Frontend ワンクリック**: ユーザーが任意のメディアに対して、Frontend のボタン押下のみでタグ・説明文・センシティブ判定を再生成できる
3. **生 SQL ゼロ**: tag_palette と CLI スクリプトに `INSERT INTO` / `UPDATE ... SET` が**1 件も残らない**
4. **サイドカーファイル不要**: 新規取り込み時に `tag_palette.json` を作らずに完結する。既存ファイルは読み込みフォールバックのみ
5. **既存機能の非後退**: Eagle ライブラリへの一括取り込みが現状の所要時間と同等で動く
6. **DB 書き込み点マップが「ORM 経由のみ」になる**: [db_writepoint_map.md](./db_writepoint_map.md) のリスク #1〜#6 が消える

---

## 8. 主要リスク（事前に認識）

| # | リスク | 緩和策 |
|---|---|---|
| 1 | GPU Worker が単一障害点になる | 5xx を明示的に返す、リトライは Frontend 側に任せる |
| 2 | HTTP 経由で大きな埋め込み（数 MB）を頻繁に運ぶオーバーヘッド | 必要な場合は base64 ではなく multipart / バイナリ POST に切替える ADR で再考 |
| 3 | `media_similar/_tagger.py` 廃止に伴う既存 API（`media_tagger/predict` / `media_similar/by-image`）の挙動変更 | 機能テストを移行前に整備、振る舞いを「呼び先が GPU Worker になっただけ」に保つ |
| 4 | tag_palette CLI を残しつつ HTTP API に切替えるとローカルでの開発体験が悪化（GPU Worker を起動する必要） | CLI に「ローカル直接実行」モードと「HTTP モード」のスイッチを残す |
| 5 | Eagle ライブラリへのアクセスを GPU Worker に開放するとパス管理が複雑化 | Worker は**画像バイト列を受け取る**設計にし、ファイルパス共有を廃止する選択肢も ADR で評価 |
| 6 | Python バージョン差（tag_palette 3.10+ / eagle 3.14） | GPU Worker は tag_palette と同じ仮想環境のままで OK。eagle backend は 3.14 を維持 |

---

## 9. 関連ドキュメント

| ドキュメント | 役割 |
|---|---|
| [integration_inventory.md](./integration_inventory.md) | tag_palette の公開 API・CLI・成果物の棚卸し |
| [db_writepoint_map.md](./db_writepoint_map.md) | DB テーブル別の書き込み点と ORM 整合分析 |
| 本文書 | 統合の動機・シナリオ・成功基準 |
| (次) `docs/adr/0001-*.md` | §6.3 の論点を 1 ファイル 1 決定で記録 |
| (次) `docs/migration_plan.md` | フェーズ分け・順序・ロールバック手順 |
