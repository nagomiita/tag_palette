"""sample画像に対してタグ生成を実行するスクリプト。

Usage:
    uv run python samples/run.py
    uv run python samples/run.py --model wd-vit-large-tagger-v3
    uv run python samples/run.py --all-models
"""

import argparse
import sys
from pathlib import Path

from tag_palette import generate_tags, get_tag_category, is_sensitive, get_translation_for_tag

SAMPLES_DIR = Path(__file__).parent
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def find_images() -> list[Path]:
    return sorted(p for p in SAMPLES_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)


def main() -> None:
    parser = argparse.ArgumentParser(description="sample画像のタグ生成")
    parser.add_argument("--model", default="wd-eva02-large-tagger-v3", help="使用するモデル名")
    parser.add_argument("--all-models", action="store_true", help="全モデルで推論")
    parser.add_argument("--threshold", type=float, default=0.35, help="タグの信頼度閾値")
    args = parser.parse_args()

    images = find_images()
    if not images:
        print(f"画像が見つかりません。{SAMPLES_DIR} に画像を配置してください。")
        sys.exit(1)

    print(f"Found {len(images)} image(s)\n")

    for image_path in images:
        print(f"{'=' * 60}")
        print(f"Image: {image_path.name}")
        print(f"{'=' * 60}")

        results = generate_tags(image_path, model_name=args.model, use_all_models=args.all_models)

        for result in results:
            print(f"\n  Model: {result.model_name}")
            print(f"  Tags ({len(result.tags)}):")

            for tag, confidence in result.tags.items():
                category = get_tag_category(tag)
                sensitive = " [SENSITIVE]" if is_sensitive(tag) else ""
                translation = get_translation_for_tag(tag)
                ja = f" ({translation})" if translation else ""

                print(f"    {confidence:.3f}  {tag}{ja}  [{category}]{sensitive}")

        print()


if __name__ == "__main__":
    main()
