"""GIF/WebM to upscaled WebM converter using imgutils CDC upscaler."""

import argparse
import io
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import cv2
import numpy as np
from PIL import Image
from imgutils.upscale.cdc import upscale_with_cdc


def extract_gif_frames(gif_path: str) -> tuple[list[Image.Image], list[int]]:
    """Extract all frames and their durations from a GIF file.

    Returns:
        Tuple of (frames, durations_ms).
    """
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
    """Get video duration in seconds using ffprobe."""
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
    """Extract all frames and FPS from a video file (WebM, MP4, etc.).

    Uses ffprobe to get the actual duration, then calculates FPS from
    the number of decoded frames. This handles VFR videos correctly.

    Returns:
        Tuple of (frames, fps).
    """
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

    # Determine correct FPS: prefer ffprobe duration over OpenCV metadata
    duration = _get_duration_ffprobe(video_path)
    if duration and duration > 0:
        fps = len(frames) / duration
    else:
        cap2 = cv2.VideoCapture(video_path)
        fps = cap2.get(cv2.CAP_PROP_FPS) or 10.0
        cap2.release()

    return frames, fps


def upscale_frames(
    frames: list[Image.Image],
    tile_size: int = 512,
    tile_overlap: int = 64,
    batch_size: int = 1,
) -> list[Image.Image]:
    """Upscale each frame using CDC X2 model applied twice (4x total)."""
    upscaled = []
    total = len(frames)
    model = "HGSR-MHR_X2_1680"
    for i, frame in enumerate(frames):
        print(f"  Upscaling frame {i + 1}/{total} (pass 1/2)...")
        result = upscale_with_cdc(
            frame, model=model,
            tile_size=tile_size, tile_overlap=tile_overlap,
            batch_size=batch_size, silent=True,
        )
        print(f"  Upscaling frame {i + 1}/{total} (pass 2/2)...")
        result = upscale_with_cdc(
            result, model=model,
            tile_size=tile_size, tile_overlap=tile_overlap,
            batch_size=batch_size, silent=True,
        )
        upscaled.append(result)
    return upscaled


def frames_to_webm(
    frames: list[Image.Image],
    fps: float,
    output_path: str,
) -> None:
    """Write frames to a WebM file (VP8 codec)."""
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
            arr = np.array(frame)
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            writer.write(bgr)
    finally:
        writer.release()


def convert_to_webm(
    input_path: str,
    output_path: str | None = None,
    tile_size: int = 512,
    tile_overlap: int = 64,
    batch_size: int = 1,
) -> str:
    """Convert a GIF or video to an upscaled WebM using CDC X2 model applied twice (4x).

    Args:
        input_path: Path to the input file (GIF, WebM, MP4, etc.).
        output_path: Path for the output WebM file.
        tile_size: Tile size for upscaling.
        tile_overlap: Tile overlap for upscaling.
        batch_size: Batch size for upscaling.

    Returns:
        Path to the output WebM file.
    """
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
    print(f"  Extracted {len(frames)} frames ({fps:.1f} fps)")

    print("[2/3] Upscaling frames with CDC X2 (2-pass, 4x total)...")
    upscaled_frames = upscale_frames(
        frames,
        tile_size=tile_size,
        tile_overlap=tile_overlap,
        batch_size=batch_size,
    )

    print(f"[3/3] Writing WebM to {output_path}...")
    frames_to_webm(upscaled_frames, fps, output_path)
    print("Done!")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert GIF/video to upscaled WebM using CDC super-resolution"
    )
    parser.add_argument("input", help="Input file path (GIF, WebM, MP4, etc.)")
    parser.add_argument("-o", "--output", help="Output WebM file path")
    parser.add_argument("--tile-size", type=int, default=512, help="Tile size for upscaling")
    parser.add_argument("--tile-overlap", type=int, default=64, help="Tile overlap for upscaling")
    parser.add_argument("--batch-size", type=int, default=1, help="Batch size for upscaling")

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: {args.input} does not exist", file=sys.stderr)
        sys.exit(1)

    convert_to_webm(
        input_path=args.input,
        output_path=args.output,
        tile_size=args.tile_size,
        tile_overlap=args.tile_overlap,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
