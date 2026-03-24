"""sample画像に対してタグ生成を実行するスクリプト。

Usage:
    uv run python samples/run.py
    uv run python samples/run.py --model ViT_Large
    uv run python samples/run.py --all-models
    uv run python samples/run.py --batch          # バッチ処理モード
"""

import argparse
import sys
import time
from pathlib import Path

from tag_palette import (
    generate_tags,
    generate_tags_batch,
    get_tag_category,
    get_translation_for_tag,
    is_sensitive_by_ratings,
)

SAMPLES_DIR = Path(__file__).parent
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def find_images() -> list[Path]:
    return sorted(
        p for p in SAMPLES_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS
    )


def print_result(result, image_name: str = "") -> None:
    if image_name:
        print(f"{'=' * 60}")
        print(f"Image: {image_name}")
        print(f"{'=' * 60}")

    print(f"\n  Model: {result.model_name}")

    # WD14 rating 表示
    if result.ratings:
        sensitive = is_sensitive_by_ratings(result.ratings)
        label = "SENSITIVE" if sensitive else "SAFE"
        ratings_str = ", ".join(f"{k}={v:.3f}" for k, v in result.ratings.items())
        print(f"  Rating: [{label}] ({ratings_str})")

    print(f"  Tags ({len(result.tags)}):")

    for tag, confidence in result.tags.items():
        category = get_tag_category(tag)
        translation = get_translation_for_tag(tag)
        ja = f" ({translation[0]})" if translation else ""
        print(f"    {confidence:.3f}  {tag}{ja}  [{category}]")


def run_sequential(images: list[Path], args: argparse.Namespace) -> None:
    for image_path in images:
        results = generate_tags(
            image_path, model_name=args.model, use_all_models=args.all_models
        )
        for result in results:
            print_result(result, image_path.name)
        print()


def run_batch(images: list[Path], args: argparse.Namespace) -> None:
    def on_batch_done(done: int, total: int) -> None:
        print(
            f"\r  Progress: {done}/{total} ({done * 100 // total}%)", end="", flush=True
        )

    results = generate_tags_batch(
        images,
        model_name=args.model,
        batch_size=args.batch_size,
        on_batch_done=on_batch_done,
    )
    print()

    for image_path, result in zip(images, results):
        print_result(result, image_path.name)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="sample画像のタグ生成")
    parser.add_argument(
        "--model", default="EVA02_Large", help="使用するモデル名"
    )
    parser.add_argument("--all-models", action="store_true", help="全モデルで推論")
    parser.add_argument(
        "--threshold", type=float, default=0.35, help="タグの信頼度閾値"
    )
    parser.add_argument("--batch", action="store_true", help="バッチ処理モード")
    parser.add_argument("--batch-size", type=int, default=4, help="バッチサイズ")
    args = parser.parse_args()

    images = find_images()
    if not images:
        print(f"画像が見つかりません。{SAMPLES_DIR} に画像を配置してください。")
        sys.exit(1)

    mode = "batch" if args.batch else "sequential"
    print(f"Found {len(images)} image(s) [mode={mode}]\n")

    start = time.perf_counter()

    if args.batch:
        run_batch(images, args)
    else:
        run_sequential(images, args)

    elapsed = time.perf_counter() - start
    print(f"Total: {elapsed:.2f}s ({elapsed / len(images):.2f}s/image)")


if __name__ == "__main__":
    main()
