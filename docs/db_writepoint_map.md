# tag_palette ↔ eagle ORM 書き込み点マップ

[integration_inventory.md](./integration_inventory.md) §4.2 を**列単位**まで掘り下げ、tag_palette の生 SQL と eagle backend の SQLAlchemy ORM 定義を突き合わせたもの。**統合時に修正が必要な箇所を機械的に拾い出すこと**が目的。

調査基準:
- tag_palette: [`src/tag_palette/importer/`](../src/tag_palette/importer/) と [`src/tag_palette/novel/ingest_local.py`](../src/tag_palette/novel/ingest_local.py)、[`src/tag_palette/novel/label_tagger.py`](../src/tag_palette/novel/label_tagger.py)、[`audio_main.py`](../audio_main.py)
- eagle: [`backend/tenant/db/orm.py`](../../eagle/backend/tenant/db/orm.py)、[`backend/tenant/db/schema.py`](../../eagle/backend/tenant/db/schema.py)、[`backend/framework/db/model/columns.py`](../../eagle/backend/framework/db/model/columns.py)

---

## 0. 凡例と前提

| 記号 | 意味 |
|---|---|
| ✅ | tag_palette が書き、ORM 定義と整合 |
| ⚠️ | 書いているが要注意（値の不整合・条件式の問題等） |
| ❌ | tag_palette が書いていない（NULL のまま）、または書けない |
| 🆕 | ORM にあるが tag_palette からは触れない列（読まれる前提） |

ORM 共通仕様 ([columns.py](../../eagle/backend/framework/db/model/columns.py)):

| Mixin | 自動付与列 |
|---|---|
| `IdTimestampMixin` | `id` (UUID v7 既定) + `created_at` (TZ aware) + `updated_at` (TZ aware, NULL 許容) |
| `CustomIdMixin` | `id` + `custom_id` (UNIQUE NULL 許容) |
| `TimestampMixin` | `created_at` + `updated_at` |

**tag_palette 側の共通挙動:**
- ID は `uuid.uuid4().hex` または自然キー（Pixiv ID、`tag_en` など）を直接使用 → ORM 既定の **UUID v7 と非互換**だが衝突は実用上無し
- `created_at` は `_now_iso()` で **ISO 8601 文字列**を渡す → ORM の `TZDateTime` (タイムゾーン付き) とフォーマット差。SQLite は文字列比較で動くが、PostgreSQL/Oracle 移行時に破綻する可能性
- `updated_at` は **常に NULL のまま**（書き込みなし）

---

## 1. テーブル別対応サマリ

tag_palette が書く全 17 テーブル × eagle ORM の対応一覧。

| テーブル | tag_palette 書き込み箇所 | ORM 列数 | tag_palette 触れる列 | カバレッジ |
|---|---|---|---|---|
| `categories` | media_importer | 4 (id, name, ts×2) | 3 | 75% |
| `genres` | media_importer | 5 (id, name, note, ts×2) | 3 | 60% |
| `tags` | media_importer | 8 | 6 | 75% |
| `tag_genres` | media_importer | 5 | 4 | 80% |
| `tag_embeddings` | media_importer | 5 | 4 | 80% |
| `media` | media_importer, desc_backfill | 26 | 17 | 65% |
| `media_tags` | media_importer | 7 | 6 | 86% |
| `media_embeddings` | media_importer, desc_backfill | 7 | 6 | 86% |
| `audio_assets` | audio_importer, audio_main.py | 14 | 9 | 64% |
| `novels` | novel_importer, ingest_local | 16 | 9 | 56% |
| `novel_series` | ingest_local | 6 | 2 | 33% |
| `novel_labels` | novel_importer, ingest_local | 5 | 2 | 40% |
| `novel_label_associations` | novel_importer, ingest_local | 5 | 3 | 60% |
| `novel_label_tags` | novel/label_tagger | 6 | 5 | 83% |
| `novel_chunks` | novel_importer, ingest_local | 10 | 5 | 50% |
| `novel_morphemes` | novel_importer, ingest_local | 5 | 3 | 60% |
| `novel_chunk_morphemes` | novel_importer, ingest_local | 6 | 4 | 67% |

**触れていない eagle ORM テーブル**（読み取りのみ／無関係）:
`media_stories`, `characters`, `media_characters`, `folders`, `folder_media`, `series_characters`, `character_tachies`, `favorite_authors`, `novel_text_replacements`, `chunk_embeddings`, `routes`, `route_chunks`, `game_projects`, `game_scenes`, `game_scene_characters`, `game_choices`, `game_scene_texts`

⚠ `chunk_embeddings` は ORM にあるが tag_palette は書いていない。ただし [`novel/embedding.py`](../src/tag_palette/novel/embedding.py) にチャンク埋め込み生成のロジックがあるので、**書き込みが意図的にスキップされている**可能性が高い（要確認）。

---

## 2. テーブル別詳細マップ

### 2.1 マスタ系

#### `categories` ([orm.py:43](../../eagle/backend/tenant/db/orm.py#L43))

書き込み元: [media_importer.py:69](../src/tag_palette/importer/media_importer.py#L69) `INSERT ... ON CONFLICT(id) DO UPDATE`

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128), PK, UUID v7 既定 | ✅ `cat.id`（CSV から） | 自然キー使用、ORM 既定をバイパス |
| `name` | String(255), UNIQUE NOT NULL | ✅ `cat.name` | UPSERT |
| `created_at` | TZDateTime NOT NULL | ⚠️ ISO 文字列 | TZ 情報なし |
| `updated_at` | TZDateTime NULL | ❌ | NULL のまま |

#### `genres` ([orm.py:65](../../eagle/backend/tenant/db/orm.py#L65))

書き込み元: [media_importer.py:84](../src/tag_palette/importer/media_importer.py#L84)

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String, PK (CustomIdMixin) | ✅ `g.key` | 例: `original`, `vocaloid` |
| `name` | String(255) NOT NULL | ✅ `g.ja or g.key` | 日本語名 |
| `note` | Text | ❌ | NULL のまま |
| `custom_id` | String(128) UNIQUE NULL | ❌ | CustomIdMixin の追加列、未使用 |
| `created_at` / `updated_at` | TZDateTime | ⚠️/❌ | 同上 |

⚠ `custom_id` 列の存在を tag_palette は知らない。ORM 経由で読んだら `None` で返ってくる。

#### `tags` ([orm.py:96](../../eagle/backend/tenant/db/orm.py#L96))

書き込み元: 4 箇所
- [media_importer.py:108](../src/tag_palette/importer/media_importer.py#L108) - danbooru タグ
- [media_importer.py:122](../src/tag_palette/importer/media_importer.py#L122) - translation_cache
- [media_importer.py:134](../src/tag_palette/importer/media_importer.py#L134) - エントリ未知タグ
- [media_importer.py:286](../src/tag_palette/importer/media_importer.py#L286) - import 時の auto-create

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128) PK | ✅ `tag_en`（英語タグ名そのまま） | 自然キー |
| `name` | String(255) NULL | ✅ 日本語名 or fallback | |
| `category_id` | String(128) FK | ✅ (danbooru のみ) / ❌ (他経路) | UPDATE 時 `category_id` を再設定 |
| `is_favorite` | bool NOT NULL default 0 | ✅ ハードコード `0` | |
| `is_sensitive` | bool NOT NULL default 0 | ❌ | ⚠ tag_palette の `is_sensitive_by_ratings()` 結果は **タグ単位ではなくメディア単位**にしか反映されていない |
| `disable` | bool NOT NULL default 0 | ✅ ハードコード `0` | |
| `created_at` / `updated_at` | TZDateTime | ⚠️/❌ | |

⚠ **`tags.is_sensitive` が常に false のまま**。eagle 側で「センシティブタグ」を別途持っているなら整合確認が必要。

#### `tag_genres` ([orm.py:136](../../eagle/backend/tenant/db/orm.py#L136))

書き込み元: [media_importer.py:148](../src/tag_palette/importer/media_importer.py#L148)

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128) PK, default=`{tag_id}__{genre_id}` | ✅ 同じ命名規則 (`f"{tag_en}__{db_tag.genre}"`) | 一致 |
| `tag_id` / `genre_id` | String(128) FK NOT NULL | ✅ | UNIQUE(tag_id, genre_id) |
| `created_at` / `updated_at` | TZDateTime | ⚠️/❌ | |

#### `tag_embeddings` ([orm.py:420](../../eagle/backend/tenant/db/orm.py#L420))

書き込み元: [media_importer.py:363](../src/tag_palette/importer/media_importer.py#L363) `sync_tag_embeddings`

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128) PK UUID v7 | ⚠️ `uuid4().hex` | **形式違うが衝突なし** |
| `tag_id` | String(128) FK UNIQUE NOT NULL | ✅ | |
| `embedding` | LargeBinary NULL | ✅ float32 bytes (384次元) | |
| `created_at` / `updated_at` | TZDateTime | ⚠️/❌ | |

---

### 2.2 メディア系

#### `media` ([orm.py:188](../../eagle/backend/tenant/db/orm.py#L188)) — **最も列数が多くギャップが集中**

書き込み元:
- [media_importer.py:259](../src/tag_palette/importer/media_importer.py#L259) — INSERT
- [media_importer.py:208-255](../src/tag_palette/importer/media_importer.py#L208) — 個別列の `UPDATE ... WHERE col IS NULL` の連発
- [desc_backfill.py:108, 186](../src/tag_palette/importer/desc_backfill.py#L108) — `desc_text` / `desc_model` UPDATE

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128) PK UUID v7 | ✅ `entry.image_id`（Eagle のID = 自然キー） | |
| `file_path` | String(1024) UNIQUE NOT NULL | ✅ `images/{id}.info/{name}` | UNIQUE 衝突時の例外ハンドラあり |
| `file_name` | String(512) NOT NULL | ✅ | |
| `file_extension` | String(32) NOT NULL default='' | ✅ | |
| `thumbnail_path` | String(1024) **UNIQUE** NOT NULL | ⚠️ `images/{id}.info/{thumbnail_name}` | thumbnail_name が空文字なら全行で `images/{id}.info/` となり UNIQUE 違反の可能性 |
| `file_created_at` | datetime NULL | ❌ | |
| `rating` | Integer NULL | ❌ | ユーザー設定列 |
| `is_sensitive` | bool NOT NULL default false | ⚠️ INSERT で `entry.is_sensitive` 渡す。UPDATE は `WHERE is_sensitive IS NULL` だが NOT NULL なので**実質常に空振り** |
| `media_type` | EnumMediaType (`image`/`video`/`manga`/`book`/`html`) | ⚠️ `IMAGE`/`VIDEO`/`MANGA`/`HTML` 大文字 | SQLAlchemy 仕様上 enum 名 (`IMAGE`) が DB 格納値。整合する。**ただし `BOOK` を tag_palette は出さない** |
| `genre_id` | String(128) FK NULL | ✅ | UPDATE は `WHERE genre_id IS NULL` |
| `parent_media_id` | String(128) FK NULL | ❌ | |
| `ai_score` | Float NULL | ✅ | UPDATE で `IS NULL` 条件 |
| `real_score` | Float NULL | ✅ | 同上 |
| `monochrome_score` | Float NULL | ✅ | 同上 |
| `classify_scores` | Text NULL (JSON) | ✅ | JSON 文字列 |
| `completeness_scores` | Text NULL (JSON) | ✅ | |
| `portrait_scores` | Text NULL (JSON) | ✅ | |
| `desc_text` | Text NULL | ✅ | desc_backfill |
| `desc_model` | String(255) NULL | ✅ | desc_backfill |
| `generation_model` | String(512) NULL | ❌ | AI 画像生成メタ、別系統 |
| `generation_prompt` | Text NULL | ❌ | |
| `transparent_path` | String(1024) UNIQUE NULL | ❌ | |
| `upscaled_path` | String(1024) UNIQUE NULL | ❌ | |
| `ocr_text` | Text NULL | ✅ | UPDATE で `IS NULL` 条件 |
| `translate_data` | Text NULL (JSON) | ❌ | |
| `created_at` / `updated_at` | TZDateTime | ⚠️/❌ | |

⚠ **`UPDATE ... WHERE col IS NULL` パターンに 2 系統のリスク:**
1. `is_sensitive`, `media_type` は ORM 上 NOT NULL（server_default あり）。**直接 SQL で INSERT すれば NULL の可能性はあるが、ORM 経由のレコードでは決して更新されない**。tag_palette → ORM 移行後は更新ロジックが死ぬ。
2. `genre_id` 等の NULL 許容列でも、初回値が確定したらそのままで「再分類」は起きない。これは設計意図と思われる。

⚠ **大文字小文字問題**: `EnumMediaType.IMAGE = "image"` と value は小文字だが、SQLAlchemy のデフォルトでは enum **name**（`IMAGE`）が DB 列に格納される。`server_default=text("'IMAGE'")` ([orm.py:226](../../eagle/backend/tenant/db/orm.py#L226)) もこれと整合。tag_palette が `"IMAGE"` を直接書く現状は OK だが、**ORM 経由で `EnumMediaType.IMAGE` を渡すと `"image"` か `"IMAGE"` か実装に依存**するため、移行時は要検証。

#### `media_tags` ([orm.py:489](../../eagle/backend/tenant/db/orm.py#L489))

書き込み元: [media_importer.py:294](../src/tag_palette/importer/media_importer.py#L294)

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128) PK, default=`{media_id}__{tag_id}__{model_name}` | ✅ 同じ命名 (`f"{media_id}__{tag_id}__{entry.model_name}"`) | 一致 |
| `media_id` / `tag_id` | String(128) FK NOT NULL | ✅ | |
| `confidence` | Float NULL | ✅ | UPSERT で更新 |
| `model_name` | String(255) NULL | ✅ | |
| `created_at` / `updated_at` | TZDateTime | ⚠️/❌ | |

#### `media_embeddings` ([orm.py:381](../../eagle/backend/tenant/db/orm.py#L381))

書き込み元:
- [media_importer.py:321](../src/tag_palette/importer/media_importer.py#L321) — INSERT
- [media_importer.py:305-318](../src/tag_palette/importer/media_importer.py#L305) — 個別列 UPDATE
- [desc_backfill.py:232, 262](../src/tag_palette/importer/desc_backfill.py#L232) — `desc_embedding`

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128) PK UUID v7 | ❌ INSERT 文に `id` を**渡していない** | **SQLite の AUTO で動いている可能性。ORM 移行時に default が動くはずだが要確認** |
| `media_id` | String(128) FK UNIQUE NOT NULL | ✅ | |
| `tag_embedding` | LargeBinary NULL | ✅ | |
| `ccip_embedding` | LargeBinary NULL | ✅ | |
| `pose_embedding` | LargeBinary NULL | ✅ | |
| `desc_embedding` | LargeBinary NULL | ✅ | desc_backfill |
| `created_at` / `updated_at` | TZDateTime | ⚠️/❌ | |

⚠ **`media_embeddings.id` が tag_palette の INSERT 文から欠落**（[media_importer.py:321](../src/tag_palette/importer/media_importer.py#L321) は 4 列しか渡していない）。SQLite は NOT NULL 違反になるはず → 現運用で動いているなら、id に DEFAULT が効いている／NULL が許容されている可能性。要 DB 実体確認。

---

### 2.3 音声系

#### `audio_assets` ([orm.py:1339](../../eagle/backend/tenant/db/orm.py#L1339))

書き込み元:
- [audio_importer.py:43](../src/tag_palette/importer/audio_importer.py#L43) — INSERT
- [audio_importer.py:35](../src/tag_palette/importer/audio_importer.py#L35) — UPDATE
- [audio_main.py:125](../audio_main.py#L125) — 同じテーブルへの INSERT (`ON CONFLICT(file_path) DO UPDATE`)

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128) PK UUID v7 | ✅ `entry.asset_id` (importer) / `audio_path.stem` (audio_main) | **2 つの経路で ID 生成方式が違う** |
| `file_path` | String(1024) UNIQUE NOT NULL | ✅ | |
| `file_name` | String(512) NOT NULL | ✅ | |
| `file_extension` | String(32) NOT NULL default='' | ✅ | |
| `audio_type` | EnumAudioType (`bgm`/`se`/`voice`) | ✅ `.upper()` (`BGM`/`SE`/`VOICE`) | 上記 media_type と同じ enum 名/値の問題 |
| `title` | String(512) NULL | ❌ | 表示名、未使用 |
| `description` | Text NULL | ✅ | タグ羅列 |
| `source_url` | String(1024) NULL | ❌ | |
| `duration_ms` | Integer NULL | ✅ | |
| `loop` | bool NOT NULL default 0 | ❌ | |
| `volume` | Float NOT NULL default 1.0 | ❌ | |
| `file_size` | Integer NULL | ✅ | |
| `sample_rate` | Integer NULL | ✅ | |
| `created_at` / `updated_at` | TZDateTime | ⚠️/❌ | |

⚠ **`audio_main.py` と `importer/audio_importer.py` で同じテーブルに 2 つのスタイル**（前者は `ON CONFLICT(file_path)`、後者は別途 SELECT で存在チェック）。挙動が違うと統合時にどちらを正とするか問題になる。

---

### 2.4 小説系

#### `novels` ([orm.py:880](../../eagle/backend/tenant/db/orm.py#L880))

書き込み元:
- [novel_importer.py:124](../src/tag_palette/importer/novel_importer.py#L124) — JSON 経由（5 列）
- [ingest_local.py:284, 327, 401](../src/tag_palette/novel/ingest_local.py#L284) — txt/pdf 直接（6〜9 列）

| ORM 列 | 型 | novel_importer | ingest_local | 備考 |
|---|---|---|---|---|
| `id` | String(128) PK | ✅ Pixiv ID or n_code | ✅ 同 | |
| `title` | String(512) NOT NULL | ✅ | ✅ | |
| `author` | String(255) NULL | ✅ | ✅ | |
| `url` | String(1024) NULL | ✅ | ✅ | |
| `description` | Text NULL | ❌ | ✅ (PDF 章のみ) | **2 系統で挙動が違う** |
| `is_favorite` | bool NOT NULL default 0 | ❌ | ❌ | |
| `is_sensitive` | bool NOT NULL default 0 | ✅ | ✅ | |
| `series_id` | String(128) FK NULL | ❌ | ✅ (PDF 章のみ) | |
| `series_seq` | Integer NOT NULL default 0 | ❌ | ✅ (PDF 章のみ) | |
| `rank` | Integer NULL | ❌ | ❌ | |
| `source_path` | String(1024) NULL | ❌ | ✅ | **novel_importer は source_path を書かない** |
| `thumbnail_media_id` | String FK NULL | ❌ | ❌ | |
| `ai_summary` / `ai_characters` / `ai_setting` / `ai_mood` / `ai_meta_updated_at` | (各種) | ❌ | ❌ | AI メタ、別系統 |
| `created_at` / `updated_at` | TZDateTime | ⚠️/❌ | ⚠️/❌ | |

⚠ **二重実装の不整合**: `novel_importer.py` は JSON 経由、`ingest_local.py` は元ファイル直読み。両者とも本番 DB に書くが、書き込み列セットが異なる。**統合時には片方に寄せる必要あり**。

#### `novel_series` ([orm.py:736](../../eagle/backend/tenant/db/orm.py#L736))

書き込み元: [ingest_local.py:379](../src/tag_palette/novel/ingest_local.py#L379)

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128) PK | ✅ n_code | |
| `name` | String(512) NOT NULL | ✅ | |
| `sort_order` | Integer NOT NULL default 0 | ❌ | |
| `is_favorite` | bool NOT NULL default 0 | ❌ | |
| `thumbnail_media_id` | String FK NULL | ❌ | |
| `created_at` / `updated_at` | TZDateTime | ⚠️/❌ | |

#### `novel_labels` ([orm.py:951](../../eagle/backend/tenant/db/orm.py#L951))

書き込み元: [novel_importer.py:35](../src/tag_palette/importer/novel_importer.py#L35), [ingest_local.py:133](../src/tag_palette/novel/ingest_local.py#L133)

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128) PK | ✅ uuid4 hex | |
| `name` | String(255) UNIQUE NOT NULL | ✅ | |
| `is_pinned` | bool NOT NULL default 0 | ❌ | |
| `is_hidden` | bool NOT NULL default 0 | ❌ | |
| `created_at` / `updated_at` | TZDateTime | ❌/❌ | **created_at すら書いていない** — server_default で動いているはず |

#### `novel_label_associations` ([orm.py:986](../../eagle/backend/tenant/db/orm.py#L986))

書き込み元: [novel_importer.py:155](../src/tag_palette/importer/novel_importer.py#L155), [ingest_local.py:208](../src/tag_palette/novel/ingest_local.py#L208)

`INSERT OR IGNORE` で書き込み。3 列 (id, novel_id, label_id) を渡す。`created_at` は server_default 任せ。

#### `novel_label_tags` ([orm.py:450](../../eagle/backend/tenant/db/orm.py#L450))

書き込み元: [label_tagger.py:227, 272](../src/tag_palette/novel/label_tagger.py#L227)

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128) PK | ✅ uuid4 hex | |
| `novel_label_id` | String FK NOT NULL | ✅ | |
| `tag_id` | String FK NOT NULL | ✅ | |
| `similarity` | Float default 0.0 | ✅ | UPSERT |
| `created_at` / `updated_at` | TZDateTime | ⚠️/❌ | |

#### `novel_chunks` ([orm.py:1081](../../eagle/backend/tenant/db/orm.py#L1081))

書き込み元: [novel_importer.py:170](../src/tag_palette/importer/novel_importer.py#L170), [ingest_local.py:228](../src/tag_palette/novel/ingest_local.py#L228)

| ORM 列 | 型 | tag_palette | 備考 |
|---|---|---|---|
| `id` | String(128) PK | ✅ uuid4 hex | |
| `novel_id` | String FK NOT NULL | ✅ | |
| `seq` | Integer NOT NULL | ✅ | |
| `kind` | String(32) NOT NULL | ✅ `dialogue`/`thought`/`narrative` | |
| `body` | Text NOT NULL | ✅ | |
| `media_id` | String FK NULL | ❌ | |
| `audio_asset_id` | String FK NULL | ❌ | |
| `is_favorite` | bool NOT NULL default 0 | ❌ | |
| `speaker` | String(255) NULL | ❌ | AI 推論列、別系統 |
| `emotion` | String(64) NULL | ❌ | 同上 |
| `created_at` / `updated_at` | TZDateTime | ❌/❌ | server_default 任せ |

⚠ **`chunk_embeddings` テーブルへの書き込みが tag_palette に無い**。[novel/embedding.py](../src/tag_palette/novel/embedding.py) は `.npy` ファイルへの保存のみで、DB 連携が抜けている。eagle 側で別途バックフィルが必要か、tag_palette から書くよう拡張するかの判断が要る。

#### `novel_morphemes` / `novel_chunk_morphemes`

書き込み元: 上記 2 系統。列対応はインベントリ表参照（パススルーで型衝突なし）。

---

## 3. 横断的な不整合パターン

詳細マップから帰納できる「全テーブルで共通の問題」をまとめる。

### 3.1 タイムスタンプ
- `created_at` を **ISO 文字列**で渡す箇所と、**渡さない（server_default 任せ）** 箇所が混在
- `updated_at` は**全テーブルで NULL のまま**
- ORM の `TZDateTime` は LOCAL_TIMEZONE を伴う → tag_palette の `datetime.now().isoformat()` は naive

→ 統合時に `created_at`/`updated_at` を ORM 側 default に任せれば自動解決。`session.add()` 経由で良い。

### 3.2 ID 生成
- ORM 既定: UUID v7（時刻順ソート可能）
- tag_palette: `uuid.uuid4().hex` または自然キー（Pixiv ID、英語タグ名）

→ **既存 DB を捨てない場合**は混在を許容するしかない。新規生成は ORM 既定に統一。

### 3.3 Enum 値の表現
- `media_type` / `audio_type` の DB 格納値は **enum name (UPPERCASE)** だが、`schemas.py` の Pydantic 値は **lowercase**
- tag_palette は直接 UPPERCASE を SQL に書いて辻褄を合わせている

→ ORM 統一後は `EnumMediaType.IMAGE` を直接渡せばよく、SQLAlchemy が name を使う設定を維持。**`schemas.py` の値も name に揃えるか、変換層を入れるかを決める必要**。

### 3.4 `UPDATE ... WHERE col IS NULL` パターンの死活
[media_importer.py:208-255](../src/tag_palette/importer/media_importer.py#L208) の連発する個別 UPDATE は、**NOT NULL 列に対しては永久に空振り**する。具体的には:
- `is_sensitive`（NOT NULL default false）
- `media_type`（NOT NULL default `IMAGE`）

→ 「再評価で値を上書きしたい」のであれば条件を見直す必要。「初回のみ書く」が意図なら NULL 許容列のみ意味がある。

### 3.5 二重実装
- 小説: `novel_importer.py`（JSON 経由）と `ingest_local.py`（元ファイル直読み）が同じテーブルに別の列セットで書く
- 音声: `audio_importer.py` と `audio_main.py` が `audio_assets` に違うフローで書く

→ 統合フェーズで片方に寄せる ADR が必要。

### 3.6 INSERT 文に必須列が欠落
- `media_embeddings.id` を tag_palette が**渡していない**にもかかわらず動いている
  → SQLite が許容しているか、DB 側に DEFAULT がある可能性。**ORM へ移行すると顕在化するリスク**。

### 3.7 ORM にあって tag_palette が触れない列
- `media`: `rating`, `parent_media_id`, `transparent_path`, `upscaled_path`, `translate_data`, `generation_model`, `generation_prompt` — eagle 側のユーザー操作・別パイプライン領域
- `novels`: `is_favorite`, `rank`, `thumbnail_media_id`, `ai_*` — 同上
- `tags`: `is_sensitive` — **タグ単位の sensitive 評価が tag_palette 側に無い**
- 各種 `novel_chunks.media_id` / `audio_asset_id` / `speaker` / `emotion` — 別系統

これらは「tag_palette は関与しない、eagle が排他的に書く」線引きとして整理可能。

---

## 4. 統合時に効くリスク（優先度付き）

| # | リスク | 該当箇所 | 影響 | 推奨アクション |
|---|---|---|---|---|
| 1 | `media_embeddings.id` が INSERT で省略されている | [media_importer.py:321](../src/tag_palette/importer/media_importer.py#L321) | ORM 移行で NOT NULL 違反の可能性 | DB 実体を確認し、ORM 経由 INSERT に統一 |
| 2 | `UPDATE ... WHERE col IS NULL` が NOT NULL 列で空振り | media_importer の UPDATE 群 | 再評価値が反映されない | 条件削除 or 列を NULL 許容に変更 |
| 3 | 小説インジェスト 2 系統 | novel_importer / ingest_local | source_path/description 等の差分発生 | 片方に寄せる ADR |
| 4 | 音声書き込み 2 系統 | audio_importer / audio_main | スタイル不整合 | 統合フェーズで一本化 |
| 5 | Enum 値の表現が name (UPPERCASE) と value (lowercase) で混在 | schemas.py vs DB 列 | 移行後の値破損 | ORM 経由を正準化、変換層をスキーマ側で吸収 |
| 6 | `chunk_embeddings` テーブルが未書き込み | novel/embedding.py | 検索機能が DB 側で動かない | バックフィルを追加 or eagle 側で処理 |
| 7 | `tags.is_sensitive` が tag_palette から書かれない | media_importer のタグ生成 | センシティブタグ検出ロジックの不整合 | 既存の `is_sensitive_by_ratings` をタグ単位にも展開 or eagle 側で別管理 |
| 8 | `created_at` が naive ISO 文字列 | 全テーブル共通 | TZ 移行時に値破損 | ORM 経由で TZ aware を強制 |
| 9 | UUID v4 と v7 の混在 | tag_palette 全体 | 機能影響なし、ソート性能のみ低下 | 新規生成のみ v7 に揃える |

---

## 5. 統合方針の示唆

このマップから自然に導ける統合方針:

1. **DB 書き込みは段階的に SQLAlchemy ORM 経由へ移行**できる。テーブル名・列名はほぼ完全一致しており、追加開発は「足りない列を埋める」よりも「不要な生 SQL を ORM call に置換する」が中心。

2. **`media_embeddings` の id 欠落と UPDATE 空振りバグ**は移行を待たずに修正可能（独立した PR で潰せる）。

3. **小説と音声の二重実装は ORM 移行の前にどちらかに寄せておく**と作業量が半減する。

4. **`chunk_embeddings` の DB 書き込み欠落**は機能的な穴なので、移行とは別に決断（書く／書かない）が必要。

5. **`tags.is_sensitive`** は tag_palette が知らない列。eagle 側がどこで設定しているかを別途確認しないと整合性が取れない。

これらは次フェーズの ADR の入力になる。
