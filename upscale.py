"""画像・動画を CDC 超解像モデルで高画質化するスクリプト"""

import argparse
import io
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import cv2
import numpy as np
from PIL import Image
from imgutils.upscale.cdc import upscale_with_cdc

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
VIDEO_EXTS = {".gif", ".webm", ".mp4", ".avi", ".mov", ".mkv"}


# ---------------------------------------------------------------------------
# 共通: アップスケール
# ---------------------------------------------------------------------------

def upscale_image(
    img: Image.Image,
    model: str = "HGSR-MHR_X2_1680",
    passes: int = 2,
    tile_size: int = 512,
    tile_overlap: int = 64,
    batch_size: int = 1,
) -> Image.Image:
    """1枚の画像を CDC モデルで高画質化する。"""
    result = img
    for p in range(passes):
        print(f"  pass {p + 1}/{passes}...")
        result = upscale_with_cdc(
            result, model=model,
            tile_size=tile_size, tile_overlap=tile_overlap,
            batch_size=batch_size, silent=True,
        )
    return result


def upscale_frames(
    frames: list[Image.Image],
    **kwargs,
) -> list[Image.Image]:
    """複数フレームを順に高画質化する。"""
    upscaled = []
    total = len(frames)
    for i, frame in enumerate(frames):
        print(f"  frame {i + 1}/{total}")
        upscaled.append(upscale_image(frame, **kwargs))
    return upscaled


# ---------------------------------------------------------------------------
# 画像
# ---------------------------------------------------------------------------

def upscale_image_file(
    input_path: str,
    output_path: str | None = None,
    **kwargs,
) -> str:
    """画像ファイルを高画質化して保存する。"""
    p = Path(input_path)
    if output_path is None:
        output_path = str(p.with_name(f"{p.stem}_upscaled{p.suffix}"))

    print(f"[1/2] Loading {input_path}...")
    img = Image.open(input_path).convert("RGB")
    print(f"  size: {img.width}x{img.height}")

    print("[2/2] Upscaling...")
    result = upscale_image(img, **kwargs)
    result.save(output_path)
    print(f"Done! {result.width}x{result.height} -> {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# 動画 / GIF
# ---------------------------------------------------------------------------

def extract_gif_frames(gif_path: str) -> tuple[list[Image.Image], list[int]]:
    """GIF から全フレームとフレーム時間を抽出する。"""
    gif = Image.open(gif_path)
    frames = []
    durations = []
    try:
        while True:
            frames.append(gif.copy().convert("RGB"))
            durations.append(gif.info.get("duration", 100))
            gif.seek(gif.tell() + 1)
    except EOFError:
        pass
    return frames, durations


def _get_duration_ffprobe(video_path: str) -> float | None:
    """ffprobe で動画の長さ (秒) を取得する。"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


def extract_video_frames(video_path: str) -> tuple[list[Image.Image], float]:
    """動画から全フレームと FPS を抽出する。"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    frames = []
    while True:
        ret, bgr = cap.read()
        if not ret:
            break
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        frames.append(Image.fromarray(rgb))
    cap.release()

    if not frames:
        raise RuntimeError(f"No frames decoded from {video_path}")

    duration = _get_duration_ffprobe(video_path)
    if duration and duration > 0:
        fps = len(frames) / duration
    else:
        cap2 = cv2.VideoCapture(video_path)
        fps = cap2.get(cv2.CAP_PROP_FPS) or 10.0
        cap2.release()

    return frames, fps


def frames_to_webm(
    frames: list[Image.Image],
    fps: float,
    output_path: str,
) -> None:
    """フレーム列を WebM (VP8) として書き出す。"""
    if not frames:
        raise ValueError("No frames to write")

    width, height = frames[0].size
    fourcc = cv2.VideoWriter_fourcc(*"VP80")
    writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    if not writer.isOpened():
        raise RuntimeError(
            f"Failed to open VideoWriter for {output_path}. "
            "Ensure OpenCV is built with VP8/WebM support."
        )
    try:
        for frame in frames:
            bgr = cv2.cvtColor(np.array(frame), cv2.COLOR_RGB2BGR)
            writer.write(bgr)
    finally:
        writer.release()


def upscale_video_file(
    input_path: str,
    output_path: str | None = None,
    **kwargs,
) -> str:
    """動画/GIF を高画質化して WebM で保存する。"""
    input_path = str(Path(input_path).resolve())
    suffix = Path(input_path).suffix.lower()

    if output_path is None:
        stem = Path(input_path).stem
        parent = Path(input_path).parent
        if suffix == ".webm":
            output_path = str(parent / f"{stem}_upscaled.webm")
        else:
            output_path = str(Path(input_path).with_suffix(".webm"))

    print(f"[1/3] Extracting frames from {input_path}...")
    if suffix == ".gif":
        frames, durations = extract_gif_frames(input_path)
        fps = 1000.0 / max(sum(durations) / len(durations), 1)
    else:
        frames, fps = extract_video_frames(input_path)
    print(f"  {len(frames)} frames ({fps:.1f} fps)")

    print("[2/3] Upscaling frames...")
    upscaled = upscale_frames(frames, **kwargs)

    print(f"[3/3] Writing WebM to {output_path}...")
    frames_to_webm(upscaled, fps, output_path)
    print("Done!")
    return output_path


# ---------------------------------------------------------------------------
# メイン: 拡張子で自動分岐
# ---------------------------------------------------------------------------

def upscale_file(input_path: str, output_path: str | None = None, **kwargs) -> str:
    """拡張子を見て画像 or 動画の高画質化を自動選択する。"""
    suffix = Path(input_path).suffix.lower()
    if suffix in IMAGE_EXTS:
        return upscale_image_file(input_path, output_path, **kwargs)
    elif suffix in VIDEO_EXTS:
        return upscale_video_file(input_path, output_path, **kwargs)
    else:
        raise ValueError(
            f"Unsupported format: {suffix}\n"
            f"  Images: {', '.join(sorted(IMAGE_EXTS))}\n"
            f"  Videos: {', '.join(sorted(VIDEO_EXTS))}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="画像・動画を CDC 超解像モデルで高画質化する"
    )
    parser.add_argument("input", help="入力ファイル (画像 or 動画)")
    parser.add_argument("-o", "--output", help="出力ファイルパス")
    parser.add_argument("--passes", type=int, default=2,
                        help="アップスケール回数 (default: 2 → 4x)")
    parser.add_argument("--tile-size", type=int, default=512,
                        help="タイルサイズ (default: 512)")
    parser.add_argument("--tile-overlap", type=int, default=64,
                        help="タイルオーバーラップ (default: 64)")
    parser.add_argument("--batch-size", type=int, default=1,
                        help="バッチサイズ (default: 1)")

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: {args.input} does not exist", file=sys.stderr)
        sys.exit(1)

    upscale_file(
        input_path=args.input,
        output_path=args.output,
        passes=args.passes,
        tile_size=args.tile_size,
        tile_overlap=args.tile_overlap,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
