"""既存の tag_palette.json を走査し、ai_score / real_score を埋め戻すスクリプト。

サブコマンド:
  compute   画像からスコアを計算して tag_palette.json に書き込む
  db        tag_palette.json のスコアを SQLite に流し込む (スコアのみ更新)

Usage:
    # スコア計算 → tag_palette.json に書き込み
    uv run python backfill_scores.py compute
    uv run python backfill_scores.py compute --only real_score
    uv run python backfill_scores.py compute --force

    # tag_palette.json → SQLite にスコアのみ反映
    uv run python backfill_scores.py db
    uv run python backfill_scores.py db --only real_score
    uv run python backfill_scores.py db --force
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif", "heic", "heif", "avif",
}


ALL_SCORE_KEYS = ("ai_score", "real_score", "monochrome_score", "classify_scores", "completeness_scores", "portrait_scores")
ALL_EMBEDDING_KEYS = ("pose_embedding",)


def _is_image(ext: str) -> bool:
    return ext.lower().strip(".") in _IMAGE_EXTENSIONS


def _find_targets(
    image_dir: Path,
    only: list[str] | None,
    force: bool,
) -> list[tuple[Path, Path, dict]]:
    """tag_palette.json がある .info ディレクトリを走査し、更新対象を返す。

    Returns:
        [(info_dir, image_path, tp_data), ...]
    """
    targets = []
    scanned = 0
    for info_dir in sorted(image_dir.iterdir()):
        if not info_dir.is_dir() or not info_dir.name.endswith(".info"):
            continue
        scanned += 1
        if scanned % 500 == 0:
            logger.info("スキャン中: %d ディレクトリ (対象: %d 件)", scanned, len(targets))

        tp_path = info_dir / "tag_palette.json"
        if not tp_path.exists():
            continue

        try:
            with open(tp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        ext = data.get("ext", "")
        if not _is_image(ext):
            continue

        # スキップ判定: force でなければ既にスコアがある項目はスキップ
        target_keys = only if only else ALL_SCORE_KEYS
        if not force:
            if all(data.get(k) is not None for k in target_keys):
                continue

        # 画像ファイル特定
        name = data.get("name", "")
        thumbnail_name = data.get("thumbnail_name", "")

        # サムネイルがあればそちらを使う (軽量)
        image_path = None
        if thumbnail_name:
            thumb = info_dir / thumbnail_name
            if thumb.exists():
                image_path = thumb
        if image_path is None:
            img = info_dir / name
            if img.exists():
                image_path = img

        if image_path is None:
            continue

        targets.append((info_dir, image_path, data))

    logger.info("スキャン完了: %d ディレクトリ → 対象: %d 件", scanned, len(targets))
    return targets


def backfill(
    image_dir: Path,
    only: list[str] | None = None,
    force: bool = False,
) -> None:
    targets = _find_targets(image_dir, only, force)
    logger.info("対象: %d 件", len(targets))

    if not targets:
        logger.info("更新対象がありません。")
        return

    # 必要なモジュールを遅延読み込み (起動高速化)
    def _should(key: str) -> bool:
        return only is None or key in only

    if _should("ai_score"):
        from imgutils.validate import get_ai_created_score
    if _should("real_score"):
        from imgutils.validate import anime_real_score
    if _should("monochrome_score"):
        from imgutils.validate import get_monochrome_score
    if _should("classify_scores"):
        from imgutils.validate import anime_classify_score
    if _should("completeness_scores"):
        from imgutils.validate import anime_completeness_score
    if _should("portrait_scores"):
        from imgutils.validate import anime_portrait_score

    updated = 0
    errors = 0

    for i, (info_dir, image_path, data) in enumerate(targets, 1):
        tp_path = info_dir / "tag_palette.json"
        changed = False

        try:
            img_str = str(image_path)

            if _should("ai_score") and (force or data.get("ai_score") is None):
                data["ai_score"] = get_ai_created_score(img_str)
                changed = True

            if _should("real_score") and (force or data.get("real_score") is None):
                scores = anime_real_score(img_str)
                data["real_score"] = scores.get("real")
                changed = True

            if _should("monochrome_score") and (force or data.get("monochrome_score") is None):
                data["monochrome_score"] = get_monochrome_score(img_str)
                changed = True

            if _should("classify_scores") and (force or data.get("classify_scores") is None):
                data["classify_scores"] = anime_classify_score(img_str)
                changed = True

            if _should("completeness_scores") and (force or data.get("completeness_scores") is None):
                data["completeness_scores"] = anime_completeness_score(img_str)
                changed = True

            if _should("portrait_scores") and (force or data.get("portrait_scores") is None):
                data["portrait_scores"] = anime_portrait_score(img_str)
                changed = True

            if changed:
                with open(tp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                updated += 1

            if i % 100 == 0 or i == len(targets):
                logger.info("進捗: %d/%d (更新: %d, エラー: %d)", i, len(targets), updated, errors)

        except Exception as e:
            errors += 1
            logger.warning("失敗: %s -> %s", info_dir.name, e)

    logger.info("完了: %d 件更新, %d 件エラー", updated, errors)


# ---------------------------------------------------------------------------
# pose サブコマンド: ポーズ埋め込みベクトルの埋め戻し
# ---------------------------------------------------------------------------


def backfill_pose(
    image_dir: Path,
    force: bool = False,
) -> None:
    """既存画像のポーズ埋め込みを pose_embedding.npy に書き出す。"""
    from tag_palette.pose_embedding import extract_pose_embedding

    targets: list[tuple[Path, Path]] = []
    scanned = 0
    for info_dir in sorted(image_dir.iterdir()):
        if not info_dir.is_dir() or not info_dir.name.endswith(".info"):
            continue
        scanned += 1
        if scanned % 500 == 0:
            logger.info("スキャン中: %d ディレクトリ (対象: %d 件)", scanned, len(targets))

        tp_path = info_dir / "tag_palette.json"
        if not tp_path.exists():
            continue

        # 既に pose_embedding.npy がある場合はスキップ
        pose_path = info_dir / "pose_embedding.npy"
        if not force and pose_path.exists():
            continue

        try:
            with open(tp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        ext = data.get("ext", "")
        if not _is_image(ext):
            continue

        # 画像ファイル特定 (サムネイル優先)
        thumbnail_name = data.get("thumbnail_name", "")
        image_path = None
        if thumbnail_name:
            thumb = info_dir / thumbnail_name
            if thumb.exists():
                image_path = thumb
        if image_path is None:
            name = data.get("name", "")
            img = info_dir / name
            if img.exists():
                image_path = img
        if image_path is None:
            continue

        targets.append((info_dir, image_path))

    logger.info("スキャン完了: %d ディレクトリ → 対象: %d 件", scanned, len(targets))

    if not targets:
        logger.info("更新対象がありません。")
        return

    updated = 0
    skipped = 0
    errors = 0

    for i, (info_dir, image_path) in enumerate(targets, 1):
        try:
            vec = extract_pose_embedding(str(image_path))
            if vec is not None:
                np.save(info_dir / "pose_embedding.npy", vec)
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            errors += 1
            logger.warning("失敗: %s -> %s", info_dir.name, e)

        if i % 100 == 0 or i == len(targets):
            logger.info("進捗: %d/%d (生成: %d, 人物なし: %d, エラー: %d)",
                        i, len(targets), updated, skipped, errors)

    logger.info("完了: %d 件生成, %d 件人物なし, %d 件エラー", updated, skipped, errors)


# ---------------------------------------------------------------------------
# db サブコマンド: tag_palette.json → SQLite にスコアのみ反映
# ---------------------------------------------------------------------------

BATCH_SIZE = 500


def _collect_scores_and_embeddings(
    image_dir: Path,
    only: list[str] | None,
) -> list[dict]:
    """tag_palette.json からスコアを、.npy から埋め込みを収集する。

    Returns:
        [{"id": ..., "ai_score": ..., "pose_embedding": bytes|None, ...}, ...]
    """
    all_target_keys = only if only else list(ALL_SCORE_KEYS) + list(ALL_EMBEDDING_KEYS)
    want_scores = any(k in ALL_SCORE_KEYS for k in all_target_keys)
    want_embeddings = any(k in ALL_EMBEDDING_KEYS for k in all_target_keys)

    results = []
    scanned = 0
    for info_dir in sorted(image_dir.iterdir()):
        if not info_dir.is_dir() or not info_dir.name.endswith(".info"):
            continue
        scanned += 1
        if scanned % 500 == 0:
            logger.info("スキャン中: %d ディレクトリ (収集: %d 件)", scanned, len(results))

        tp_path = info_dir / "tag_palette.json"
        if not tp_path.exists():
            continue

        try:
            with open(tp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        image_id = data.get("id") or info_dir.name.removesuffix(".info")

        row = {"id": image_id}
        has_any = False

        # スコア収集
        if want_scores:
            for key in ALL_SCORE_KEYS:
                val = data.get(key)
                row[key] = val
                if key in all_target_keys and val is not None:
                    has_any = True

        # 埋め込み収集
        if want_embeddings and "pose_embedding" in all_target_keys:
            pose_path = info_dir / "pose_embedding.npy"
            if pose_path.exists():
                try:
                    arr = np.load(pose_path)
                    row["pose_embedding"] = arr.astype(np.float32).tobytes()
                    has_any = True
                except Exception as e:
                    logger.warning("pose_embedding.npy 読み込み失敗: %s -> %s", pose_path, e)
                    row["pose_embedding"] = None
            else:
                row["pose_embedding"] = None

        if not has_any:
            continue

        results.append(row)

    logger.info("スキャン完了: %d ディレクトリ → 対象: %d 件", scanned, len(results))
    return results


def backfill_db(
    image_dir: Path,
    db_path: Path,
    only: list[str] | None = None,
    force: bool = False,
) -> None:
    """tag_palette.json のスコアと .npy の埋め込みを SQLite に流し込む。"""
    rows = _collect_scores_and_embeddings(image_dir, only)
    if not rows:
        logger.info("更新対象がありません。")
        return

    all_target_keys = only if only else list(ALL_SCORE_KEYS) + list(ALL_EMBEDDING_KEYS)
    target_score_keys = [k for k in all_target_keys if k in ALL_SCORE_KEYS]
    target_emb_keys = [k for k in all_target_keys if k in ALL_EMBEDDING_KEYS]

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # dict 型スコアは JSON 文字列で格納
    dict_keys = {"classify_scores", "completeness_scores", "portrait_scores"}

    scores_updated = 0
    emb_updated = 0

    for batch in _chunked(rows, BATCH_SIZE):
        for row in batch:
            image_id = row["id"]

            # スコア更新 (media テーブル)
            for key in target_score_keys:
                val = row.get(key)
                if val is None:
                    continue
                db_val = json.dumps(val) if key in dict_keys else val
                if force:
                    conn.execute(
                        f"UPDATE media SET {key} = ? WHERE id = ?",
                        (db_val, image_id),
                    )
                else:
                    conn.execute(
                        f"UPDATE media SET {key} = ? WHERE id = ? AND {key} IS NULL",
                        (db_val, image_id),
                    )
                scores_updated += 1

            # 埋め込み更新 (media_embeddings テーブル)
            for key in target_emb_keys:
                val = row.get(key)
                if val is None:
                    continue
                # 既存行があるか確認
                existing = conn.execute(
                    "SELECT 1 FROM media_embeddings WHERE media_id = ?",
                    (image_id,),
                ).fetchone()
                if existing:
                    if force:
                        conn.execute(
                            f"UPDATE media_embeddings SET {key} = ? WHERE media_id = ?",
                            (val, image_id),
                        )
                    else:
                        conn.execute(
                            f"UPDATE media_embeddings SET {key} = ? WHERE media_id = ? AND {key} IS NULL",
                            (val, image_id),
                        )
                else:
                    conn.execute(
                        f"INSERT INTO media_embeddings (media_id, {key}) VALUES (?, ?)",
                        (image_id, val),
                    )
                emb_updated += 1

        conn.commit()

    conn.close()
    logger.info("完了: スコア %d 件, 埋め込み %d 件 更新", scores_updated, emb_updated)


def _chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    from env_config import get_db_path, get_image_dir

    parser = argparse.ArgumentParser(
        description="画像分類スコアの埋め戻しツール"
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    ALL_ONLY_CHOICES = list(ALL_SCORE_KEYS) + list(ALL_EMBEDDING_KEYS)

    # 共通引数を追加するヘルパー
    def _add_common(p, include_embeddings: bool = False):
        p.add_argument(
            "--image-dir", type=Path, default=get_image_dir(),
            help="Eagle ライブラリの images ディレクトリ (env: EAGLE_IMAGE_DIR)",
        )
        choices = ALL_ONLY_CHOICES if include_embeddings else list(ALL_SCORE_KEYS)
        p.add_argument(
            "--only", choices=choices, action="append",
            help="指定したキーのみ対象 (複数指定可, 省略時は全て)",
        )
        p.add_argument(
            "--force", action="store_true",
            help="既にスコアがあっても再計算/上書きする",
        )
        p.add_argument("--log-file", type=Path, default=None)

    # --- compute サブコマンド ---
    p_compute = sub.add_parser("compute", help="画像からスコアを計算し tag_palette.json に書き込む")
    _add_common(p_compute)

    # --- db サブコマンド ---
    p_db = sub.add_parser("db", help="スコアと埋め込みを SQLite に流し込む")
    _add_common(p_db, include_embeddings=True)
    p_db.add_argument(
        "--db-path", type=Path, default=get_db_path(),
        help="SQLite DBファイルパス (env: SQLITE_DB_PATH)",
    )

    # --- pose サブコマンド ---
    p_pose = sub.add_parser("pose", help="ポーズ埋め込みベクトルを生成し pose_embedding.npy に保存")
    p_pose.add_argument(
        "--image-dir", type=Path, default=get_image_dir(),
        help="Eagle ライブラリの images ディレクトリ (env: EAGLE_IMAGE_DIR)",
    )
    p_pose.add_argument(
        "--force", action="store_true",
        help="既に pose_embedding.npy があっても再計算する",
    )
    p_pose.add_argument("--log-file", type=Path, default=None)

    args = parser.parse_args()

    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )

    if not args.image_dir or not args.image_dir.is_dir():
        logger.error("--image-dir または環境変数 EAGLE_IMAGE_DIR を指定してください")
        sys.exit(1)

    if args.mode == "compute":
        backfill(
            image_dir=args.image_dir,
            only=args.only,
            force=args.force,
        )
    elif args.mode == "db":
        if not args.db_path:
            logger.error("--db-path または環境変数 SQLITE_DB_PATH を指定してください")
            sys.exit(1)
        if not args.db_path.exists():
            logger.error("DBファイルが見つかりません: %s", args.db_path)
            sys.exit(1)
        backfill_db(
            image_dir=args.image_dir,
            db_path=args.db_path,
            only=args.only,
            force=args.force,
        )
    elif args.mode == "pose":
        backfill_pose(
            image_dir=args.image_dir,
            force=args.force,
        )


if __name__ == "__main__":
    main()
