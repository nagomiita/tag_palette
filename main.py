"""タスクスケジューラから呼び出すメディアタグ生成スクリプト。

Eagle ライブラリの images ディレクトリをスキャンし、前回実行以降に追加された
画像・音声に対してタグを生成し、Eagle の metadata.json に書き戻す。

- 画像: WD14 Tagger でタグ生成
- 音声: PANNs で分類タグ生成 (Voice は Whisper で文字起こし)

前回実行時刻は状態ファイル (.last_run) に記録され、次回実行時に
それ以降に更新されたファイルのみを対象とする。

Usage:
    uv run python main.py --image-dir /path/to/eagle.library/images
    uv run python main.py --image-dir /path/to/eagle.library/images --model EVA02_Large
    uv run python main.py --image-dir /path/to/eagle.library/images --force
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from tag_palette import (
    generate_tags,
    load_tag_embeddings,
    load_translation_cache,
    save_tag_embeddings,
    save_translation_cache,
    tags_to_embedding,
    translate_tags,
)
from tag_palette.sensitive import detect_sensitive
from tag_palette._csv_reader import load_clean_tag_csv
from tag_palette.genre import _get_genre_df

_danbooru_df = None


def _get_danbooru_df():
    global _danbooru_df
    if _danbooru_df is None:
        _danbooru_df = load_clean_tag_csv(require_ja=False)
    return _danbooru_df


def detect_genre(tags: dict[str, float]) -> str | None:
    """タグ辞書から最も信頼度の高いタグのジャンルを返す。見つからなければ None。"""
    df = _get_danbooru_df()
    for tag_name in sorted(tags, key=tags.get, reverse=True):
        if tag_name in df.index:
            genre = str(df.loc[tag_name, "genre"]).strip()
            if genre:
                return genre
    return None


def get_genre_ja(genre_key: str) -> str:
    """genre.csv からジャンルの日本語名を取得する。見つからなければキーをそのまま返す。"""
    genre_df = _get_genre_df()
    if genre_key in genre_df.index:
        ja = str(genre_df.loc[genre_key, "ja"]).strip()
        if ja:
            return ja
    return genre_key


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus"}
NOVEL_EXTENSIONS = {".txt", ".pdf"}
THUMBNAIL_SIZE = (300, 300)
STATE_FILE = Path("last_run.txt")
SAVE_INTERVAL = 100

logger = logging.getLogger(__name__)


def setup_logging(log_file: Path | None = None) -> None:
    """ログ設定。ファイル指定時はファイルにも出力。"""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


# ── 前回実行時刻の管理 ──────────────────────────────────


def _state_path(image_dir: Path) -> Path:
    """image_dir の親ディレクトリ (eagle.library/) に .last_run ファイルを配置。"""
    return image_dir.parent / STATE_FILE


def load_last_run(image_dir: Path) -> datetime | None:
    """前回実行時刻を読み込む。初回は None。"""
    path = _state_path(image_dir)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return datetime.fromisoformat(text)
    except (ValueError, OSError):
        return None


def save_last_run(image_dir: Path, run_time: datetime) -> None:
    """実行時刻を状態ファイルに書き込む。"""
    path = _state_path(image_dir)
    path.write_text(run_time.isoformat(), encoding="utf-8")


# ── Eagle 画像探索 ──────────────────────────────────────


@dataclass
class EagleImage:
    """Eagle ライブラリの1画像エントリ。"""

    info_dir: Path  # {ID}.info ディレクトリ
    image_path: Path  # 元画像ファイルパス
    thumbnail_path: Path  # サムネイルパス ({name}_thumbnail.png)
    metadata_path: Path  # metadata.json パス
    eagle_id: str  # Eagle ID
    name: str  # 画像名
    ext: str  # 拡張子


def find_eagle_images(
    image_dir: Path,
    since: datetime | None,
    skip_processed: bool = True,
) -> list[EagleImage]:
    """Eagle images ディレクトリから対象画像を探索。

    - *.info/ ディレクトリを走査
    - metadata.json を読み取り、isDeleted=true / 既にタグ付き をスキップ
    - since 以降に更新されたもののみ対象 (since=None なら全件)
    """
    cutoff = since.timestamp() if since else 0

    images: list[EagleImage] = []
    for info_dir in sorted(image_dir.iterdir()):
        if not info_dir.is_dir() or not info_dir.name.endswith(".info"):
            continue

        # フォルダ作成日時チェック (= Eagle へのインポート日時) を最初に行う
        st = info_dir.stat()
        ctime = getattr(st, "st_birthtime", st.st_ctime)
        if ctime < cutoff:
            continue

        # 既処理スキップ (tag_palette.json が既にある場合)
        if skip_processed and (info_dir / "tag_palette.json").exists():
            continue

        metadata_path = info_dir / "metadata.json"
        if not metadata_path.exists():
            continue

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("metadata.json 読み込み失敗: %s -> %s", info_dir.name, e)
            continue

        # 削除済みはスキップ
        if meta.get("isDeleted", False):
            continue

        # 画像ファイルを特定
        name = meta.get("name", "")
        ext = meta.get("ext", "")
        if not name or not ext:
            continue

        image_path = info_dir / f"{name}.{ext}"
        if not image_path.exists():
            logger.warning("ファイルが見つかりません: %s", image_path)
            continue

        eagle_id = meta.get("id", info_dir.name.replace(".info", ""))
        thumbnail_path = info_dir / f"{name}_thumbnail.png"
        images.append(
            EagleImage(
                info_dir=info_dir,
                image_path=image_path,
                thumbnail_path=thumbnail_path,
                metadata_path=metadata_path,
                eagle_id=eagle_id,
                name=name,
                ext=ext,
            )
        )

    return images


# ── HEIC → WebP 変換 ─────────────────────────────────────


def convert_heic_to_webp(eagle_image: EagleImage, quality: int = 90) -> None:
    """HEIC 画像を WebP に変換し、metadata.json を更新、元ファイルを削除する。"""
    if eagle_image.ext.lower() != "heic":
        return

    from pillow_heif import register_heif_opener
    register_heif_opener()

    webp_path = eagle_image.info_dir / f"{eagle_image.name}.webp"
    try:
        with Image.open(eagle_image.image_path) as img:
            img.save(webp_path, "WEBP", quality=quality)

        # metadata.json の ext を更新
        with open(eagle_image.metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["ext"] = "webp"
        with open(eagle_image.metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        # 元ファイル削除
        eagle_image.image_path.unlink()

        # EagleImage を更新
        eagle_image.ext = "webp"
        eagle_image.image_path = webp_path

        logger.info("HEIC → WebP 変換: %s", webp_path.name)
    except Exception as e:
        logger.error("HEIC 変換失敗: %s -> %s", eagle_image.eagle_id, e)
        # 中途半端な webp が残っていたら削除
        if webp_path.exists() and eagle_image.image_path.exists():
            webp_path.unlink()


# ── サムネイル生成 ──────────────────────────────────────


def is_image_file(eagle_image: EagleImage) -> bool:
    """画像ファイルかどうかを判定する。"""
    return f".{eagle_image.ext}".lower() in IMAGE_EXTENSIONS


def is_eagle_audio_file(eagle_image: EagleImage) -> bool:
    """音声ファイルかどうかを判定する。"""
    return f".{eagle_image.ext}".lower() in AUDIO_EXTENSIONS


def is_eagle_novel_file(eagle_image: EagleImage) -> bool:
    """小説ファイルかどうかを判定する。"""
    return f".{eagle_image.ext}".lower() in NOVEL_EXTENSIONS


def ensure_thumbnail(eagle_image: EagleImage) -> None:
    """サムネイルが存在しなければ生成する。画像は PIL、動画は ffmpeg を使用。"""
    if eagle_image.thumbnail_path.exists():
        return
    if is_image_file(eagle_image):
        try:
            with Image.open(eagle_image.image_path) as img:
                img = img.convert("RGB")
                img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                img.save(eagle_image.thumbnail_path, "PNG")
            logger.info("サムネイル生成 (画像): %s", eagle_image.thumbnail_path.name)
        except Exception as e:
            logger.error("サムネイル生成失敗: %s -> %s", eagle_image.eagle_id, e)
    else:
        try:
            w, h = THUMBNAIL_SIZE
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    str(eagle_image.image_path),
                    "-vframes",
                    "1",
                    "-vf",
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease",
                    str(eagle_image.thumbnail_path),
                ],
                capture_output=True,
                check=True,
            )
            logger.info("サムネイル生成 (動画): %s", eagle_image.thumbnail_path.name)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error("動画サムネイル生成失敗: %s -> %s", eagle_image.eagle_id, e)


# ── Eagle metadata.json への書き戻し ────────────────────


def write_tags_to_eagle(
    eagle_image: EagleImage,
    tags: dict[str, float],
    model_name: str,
    ratings: dict[str, float] | None = None,
) -> None:
    """タグの日本語訳を Eagle の metadata.json の annotation に書き込み、
    tag_palette.json にタグ生データを保存する。"""
    tag_names = list(tags.keys())
    ja_tags = translate_tags(tag_names)

    # ジャンル検出
    genre = detect_genre(tags)

    # Eagle metadata.json に annotation と tags 書き込み
    try:
        with open(eagle_image.metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        meta["annotation"] = ", ".join(ja_tags)

        # genre が見つかれば Eagle の tags に日本語名を追加
        if genre:
            eagle_tags: list[str] = meta.get("tags", [])
            genre_ja = get_genre_ja(genre)
            if genre_ja not in eagle_tags:
                eagle_tags.append(genre_ja)
                meta["tags"] = eagle_tags

        with open(eagle_image.metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except Exception as e:
        logger.error("metadata.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    # 埋め込みベクトル生成 → .npy 保存
    try:
        embedding_bytes = tags_to_embedding(tags)
        if embedding_bytes:
            embedding_arr = np.frombuffer(embedding_bytes, dtype=np.float32)
            npy_path = eagle_image.info_dir / "embedding.npy"
            np.save(npy_path, embedding_arr)
    except Exception as e:
        logger.error("埋め込み生成失敗: %s -> %s", eagle_image.eagle_id, e)

    # CCIP キャラクター特徴ベクトル生成 → .npy 保存
    if is_image_file(eagle_image):
        ccip_path = eagle_image.info_dir / "ccip_embedding.npy"
        if not ccip_path.exists():
            try:
                from imgutils.metrics import ccip_extract_feature

                target = eagle_image.thumbnail_path if eagle_image.thumbnail_path.exists() else eagle_image.image_path
                feat = ccip_extract_feature(str(target))
                np.save(ccip_path, feat.astype(np.float32))
            except Exception as e:
                logger.warning("CCIP 抽出失敗: %s -> %s", eagle_image.eagle_id, e)

    # ポーズ埋め込みベクトル生成 → .npy 保存
    if is_image_file(eagle_image):
        pose_path = eagle_image.info_dir / "pose_embedding.npy"
        if not pose_path.exists():
            try:
                from tag_palette.pose_embedding import extract_pose_embedding

                target = eagle_image.thumbnail_path if eagle_image.thumbnail_path.exists() else eagle_image.image_path
                pose_vec = extract_pose_embedding(str(target))
                if pose_vec is not None:
                    np.save(pose_path, pose_vec)
            except Exception as e:
                logger.warning("ポーズ抽出失敗: %s -> %s", eagle_image.eagle_id, e)

    # 画像分類スコア判定
    ai_score: float | None = None
    real_score: float | None = None
    monochrome_score: float | None = None
    classify_scores: dict[str, float] | None = None
    completeness_scores: dict[str, float] | None = None
    portrait_scores: dict[str, float] | None = None
    if is_image_file(eagle_image):
        target = eagle_image.thumbnail_path if eagle_image.thumbnail_path.exists() else eagle_image.image_path
        target_str = str(target)

        try:
            from imgutils.validate import get_ai_created_score
            ai_score = get_ai_created_score(target_str)
        except Exception as e:
            logger.warning("AI 判定失敗: %s -> %s", eagle_image.eagle_id, e)

        try:
            from imgutils.validate import anime_real_score
            scores = anime_real_score(target_str)
            real_score = scores.get("real")
        except Exception as e:
            logger.warning("実写判定失敗: %s -> %s", eagle_image.eagle_id, e)

        try:
            from imgutils.validate import get_monochrome_score
            monochrome_score = get_monochrome_score(target_str)
        except Exception as e:
            logger.warning("モノクロ判定失敗: %s -> %s", eagle_image.eagle_id, e)

        try:
            from imgutils.validate import anime_classify_score
            classify_scores = anime_classify_score(target_str)
        except Exception as e:
            logger.warning("分類判定失敗: %s -> %s", eagle_image.eagle_id, e)

        try:
            from imgutils.validate import anime_completeness_score
            completeness_scores = anime_completeness_score(target_str)
        except Exception as e:
            logger.warning("完成度判定失敗: %s -> %s", eagle_image.eagle_id, e)

        try:
            from imgutils.validate import anime_portrait_score
            portrait_scores = anime_portrait_score(target_str)
        except Exception as e:
            logger.warning("構図判定失敗: %s -> %s", eagle_image.eagle_id, e)

    # tag_palette.json にタグ生データ保存
    try:
        tp_path = eagle_image.info_dir / "tag_palette.json"

        # 統合センシティブ判定 (WD14 rating → anime_rating → タグ辞書)
        image_for_rating = None
        if is_image_file(eagle_image):
            target = eagle_image.thumbnail_path if eagle_image.thumbnail_path.exists() else eagle_image.image_path
            image_for_rating = str(target)

        sensitive_result = detect_sensitive(
            ratings=ratings,
            image=image_for_rating,
        )

        tp_data = {
            "id": eagle_image.eagle_id,
            "name": eagle_image.image_path.name,
            "thumbnail_name": eagle_image.thumbnail_path.name,
            "ext": eagle_image.ext,
            "genre": genre,
            "is_sensitive": sensitive_result["is_sensitive"],
            "sensitive_method": sensitive_result["method"],
            "wd14_ratings": sensitive_result["wd14_ratings"],
            "anime_rating": sensitive_result["anime_rating"],
            "ai_score": ai_score,
            "real_score": real_score,
            "monochrome_score": monochrome_score,
            "classify_scores": classify_scores,
            "completeness_scores": completeness_scores,
            "portrait_scores": portrait_scores,
            "model_name": model_name,
            "tags": tags,
            "tags_ja": dict(zip(tag_names, ja_tags)),
            "generated_at": datetime.now().isoformat(),
        }
        with open(tp_path, "w", encoding="utf-8") as f:
            json.dump(tp_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("tag_palette.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)


# ── 音声タグの Eagle 書き戻し ─────────────────────────────


def write_audio_tags_to_eagle(
    eagle_image: EagleImage,
    result,
) -> None:
    """音声タグ結果を Eagle の metadata.json と tag_palette.json に保存する。"""
    from tag_palette.audio_labels_ja import get_japanese_description

    # 日本語説明を生成
    desc_ja = get_japanese_description(
        result.tags, result.audio_type.value, result.transcript,
    )

    # Eagle metadata.json に annotation 書き込み
    try:
        with open(eagle_image.metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        meta["annotation"] = desc_ja

        # audio_type を Eagle の tags に追加
        eagle_tags: list[str] = meta.get("tags", [])
        type_label = result.audio_type.value.upper()
        if type_label not in eagle_tags:
            eagle_tags.append(type_label)
            meta["tags"] = eagle_tags

        with open(eagle_image.metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except Exception as e:
        logger.error("metadata.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    # tag_palette.json に保存 (audio_assets テーブルに対応)
    try:
        tp_path = eagle_image.info_dir / "tag_palette.json"
        file_size = eagle_image.image_path.stat().st_size if eagle_image.image_path.exists() else None
        tp_data = {
            "id": eagle_image.eagle_id,
            "file_path": str(eagle_image.image_path),
            "file_name": eagle_image.image_path.name,
            "file_extension": eagle_image.ext,
            "media_type": "audio",
            "audio_type": result.audio_type.value,
            "duration_ms": result.duration_ms,
            "sample_rate": result.sample_rate,
            "file_size": file_size,
            "description": desc_ja,
            "transcript": result.transcript,
            "model_name": result.model_name,
            "tags": result.tags,
            "generated_at": datetime.now().isoformat(),
        }
        with open(tp_path, "w", encoding="utf-8") as f:
            json.dump(tp_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("tag_palette.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)


# ── 小説の解析・Eagle 書き戻し ────────────────────────────


def _parse_novel(eagle_image: EagleImage) -> dict:
    """小説ファイルを解析してメタデータを返す。"""
    ext = eagle_image.ext.lower()
    file_path = eagle_image.image_path

    if ext == "pdf":
        from tag_palette.novel.pdf_parser import parse_pdf
        novel = parse_pdf(file_path)
        return {
            "novel_id": novel.n_code,
            "title": novel.title,
            "author": novel.author,
            "url": novel.url,
            "tags": novel.tags,
            "body": novel.body,
            "is_sensitive": novel.is_sensitive,
        }

    # .txt (Pixiv / Fanbox format)
    text = file_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    url = lines[0].strip() if len(lines) > 0 else ""
    author = lines[2].strip() if len(lines) > 2 else ""
    title = eagle_image.name
    tag_line = lines[6].strip() if len(lines) > 6 else ""

    tags: list[str] = []
    if tag_line.startswith("Tags:"):
        tags = [t.strip() for t in tag_line[5:].split(",") if t.strip()]
        body = "\n".join(lines[8:])
    else:
        body = "\n".join(lines[6:])

    sensitive_tags = {"18禁", "R-18", "R18"}
    is_sensitive = any(t.strip() in sensitive_tags for t in tags)

    return {
        "novel_id": eagle_image.eagle_id,
        "title": title,
        "author": author,
        "url": url,
        "tags": tags,
        "body": body,
        "is_sensitive": is_sensitive,
    }


def write_novel_to_eagle(eagle_image: EagleImage) -> dict:
    """小説ファイルを解析し、tag_palette.json に保存する。

    Returns:
        解析結果の概要。
    """
    data = _parse_novel(eagle_image)

    # チャンク分割
    from tag_palette.novel.chunker import chunk_text
    chunks = chunk_text(data["body"])

    # 形態素解析
    from tag_palette.novel.morpheme import extract_morphemes
    morpheme_summary: dict[str, int] = {}
    for chunk in chunks:
        for (surface, _pos), count in extract_morphemes(chunk.body).items():
            morpheme_summary[surface] = morpheme_summary.get(surface, 0) + count

    # Eagle metadata.json に annotation 書き込み
    try:
        with open(eagle_image.metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        # タイトルと作者を annotation に
        annotation_parts = [data["title"]]
        if data["author"]:
            annotation_parts.append(data["author"])
        if data["tags"]:
            annotation_parts.append(", ".join(data["tags"][:5]))
        meta["annotation"] = " / ".join(annotation_parts)

        # タグを Eagle tags に追加
        eagle_tags: list[str] = meta.get("tags", [])
        for tag in data["tags"]:
            if tag not in eagle_tags:
                eagle_tags.append(tag)
        if "小説" not in eagle_tags:
            eagle_tags.append("小説")
        meta["tags"] = eagle_tags

        with open(eagle_image.metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except Exception as e:
        logger.error("metadata.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    # tag_palette.json に保存
    try:
        tp_path = eagle_image.info_dir / "tag_palette.json"
        tp_data = {
            "id": data["novel_id"],
            "media_type": "novel",
            "title": data["title"],
            "author": data["author"],
            "url": data["url"],
            "tags": data["tags"],
            "is_sensitive": data["is_sensitive"],
            "num_chunks": len(chunks),
            "num_morphemes": len(morpheme_summary),
            "chunks": [
                {"seq": c.seq, "kind": c.kind, "body": c.body}
                for c in chunks
            ],
            "morphemes": morpheme_summary,
            "generated_at": datetime.now().isoformat(),
        }
        with open(tp_path, "w", encoding="utf-8") as f:
            json.dump(tp_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("tag_palette.json 書き込み失敗: %s -> %s", eagle_image.eagle_id, e)

    return {
        "title": data["title"],
        "author": data["author"],
        "num_chunks": len(chunks),
        "num_morphemes": len(morpheme_summary),
        "num_tags": len(data["tags"]),
    }


# ── メイン ──────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Eagle ライブラリの画像にタグを生成 (タスクスケジューラ用)"
    )
    from env_config import get_image_dir

    parser.add_argument(
        "--image-dir",
        type=Path,
        default=get_image_dir(),
        help="Eagle ライブラリの images ディレクトリ (env: EAGLE_IMAGE_DIR)",
    )
    parser.add_argument("--log-file", type=Path, default=None, help="ログファイルパス")
    parser.add_argument(
        "--model", default="EVA02_Large", help="使用するモデル名"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="全画像を再処理する (タグ付き画像もスキップしない)",
    )
    args = parser.parse_args()

    setup_logging(args.log_file)

    if not args.image_dir:
        parser.error("--image-dir または環境変数 EAGLE_IMAGE_DIR を指定してください")
    if not args.image_dir.is_dir():
        logger.error("ディレクトリが見つかりません: %s", args.image_dir)
        sys.exit(1)

    # 今回の実行時刻を記録 (探索前に取得)
    run_time = datetime.now()

    # 前回実行時刻
    if args.force:
        since = None
        logger.info("--force: 全画像を対象にします")
    else:
        since = load_last_run(args.image_dir)
        if since:
            logger.info("前回実行: %s", since.isoformat())
        else:
            logger.info("初回実行: 全画像を対象にします")

    # キャッシュ読み込み
    load_translation_cache()
    load_tag_embeddings()

    # Eagle 画像探索
    images = find_eagle_images(
        args.image_dir, since=since, skip_processed=not args.force
    )
    logger.info("対象画像数: %d", len(images))

    if not images:
        logger.info("処理対象の画像がありません。")
        save_last_run(args.image_dir, run_time)
        return

    # タグ生成 → Eagle に書き戻し
    start = time.perf_counter()
    processed = 0

    for i, eagle_image in enumerate(images, 1):
        logger.info("(%d/%d) %s", i, len(images), eagle_image.image_path.name)

        if is_eagle_audio_file(eagle_image):
            # ── 音声処理 ──
            try:
                from tag_palette.audio_tagger import detect_type_from_path, generate_audio_tags

                audio_type_override = detect_type_from_path(eagle_image.image_path)
                audio_result = generate_audio_tags(
                    eagle_image.image_path,
                    audio_type_override=audio_type_override,
                )
                write_audio_tags_to_eagle(eagle_image, audio_result)
                processed += 1
                logger.info(
                    "  Audio: %s (%s, %dms)",
                    audio_result.audio_type.value,
                    audio_result.model_name,
                    audio_result.duration_ms or 0,
                )
            except Exception as e:
                logger.error("Failed (audio): %s -> %s", eagle_image.eagle_id, e)
        elif is_eagle_novel_file(eagle_image):
            # ── 小説処理 ──
            try:
                novel_info = write_novel_to_eagle(eagle_image)
                processed += 1
                logger.info(
                    "  Novel: %s (%s, %d chunks, %d morphemes)",
                    novel_info["title"],
                    novel_info["author"],
                    novel_info["num_chunks"],
                    novel_info["num_morphemes"],
                )
            except Exception as e:
                logger.error("Failed (novel): %s -> %s", eagle_image.eagle_id, e)
        else:
            # ── 画像/動画処理 ──
            convert_heic_to_webp(eagle_image)
            ensure_thumbnail(eagle_image)

            # サムネイルが無ければスキップ
            if not eagle_image.thumbnail_path.exists():
                logger.warning(
                    "サムネイルが見つかりません (スキップ): %s", eagle_image.eagle_id
                )
                continue

            try:
                tag_results = generate_tags(
                    eagle_image.thumbnail_path, model_name=args.model
                )
                if tag_results:
                    write_tags_to_eagle(
                        eagle_image,
                        tag_results[0].tags,
                        tag_results[0].model_name,
                        ratings=tag_results[0].ratings,
                    )
                    processed += 1
                    if processed % SAVE_INTERVAL == 0:
                        save_translation_cache()
                        save_tag_embeddings()
                        logger.info("キャッシュ保存 (%d件処理済み)", processed)
            except Exception as e:
                logger.error("Failed: %s -> %s", eagle_image.eagle_id, e)

    elapsed = time.perf_counter() - start
    logger.info(
        "完了: %d/%d 件 (%.2fs, %.2fs/image)",
        processed,
        len(images),
        elapsed,
        elapsed / max(len(images), 1),
    )

    # キャッシュ保存
    save_translation_cache()
    save_tag_embeddings()

    # 実行時刻を記録
    save_last_run(args.image_dir, run_time)


if __name__ == "__main__":
    main()
