from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

from core.settings import settings


class DemoAssetError(RuntimeError):
    pass


def ensure_golden_demo_assets(data_dir: Path | None = None) -> dict[str, str]:
    """Ensure golden demo clip + ground truth exist, generating deterministically if needed.

    Returns relative paths for scenario wiring.
    """
    base = data_dir or Path(settings.data_dir)
    demo_dir = base / "demo"
    clip_path = demo_dir / "demo.mp4"
    gt_path = demo_dir / "demo_annotations.json"

    demo_dir.mkdir(parents=True, exist_ok=True)

    if clip_path.exists() and gt_path.exists():
        return {"clip": "demo/demo.mp4", "ground_truth": "demo/demo_annotations.json"}

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise DemoAssetError("ffmpeg/ffprobe not found on PATH (required to generate demo assets)")

    # Tiny, deterministic clip: dark background + moving bright rectangle.
    fps = 15
    duration_sec = 4
    width = 320
    height = 180
    total_frames = fps * duration_sec

    filter_complex = (
        "[0:v][1:v]overlay=x='10+35*t':y='70+18*sin(PI*t/2)'[moved];"
        "[moved]format=yuv420p[out]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x0b1322:s={width}x{height}:r={fps}:d={duration_sec}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=white:s=18x12:r={fps}:d={duration_sec}",
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "33",
        "-movflags",
        "+faststart",
        str(clip_path),
    ]
    process = subprocess.run(cmd, capture_output=True, text=True)
    if process.returncode != 0:
        raise DemoAssetError(f"ffmpeg failed generating demo clip: {process.stderr.strip()}")

    # Ground truth boxes aligned with overlay expression above.
    annotations: dict[str, list[dict[str, object]]] = {}
    for frame_idx in range(total_frames):
        t = frame_idx / fps
        x = int(round(10 + 35 * t))
        y = int(round(70 + 18 * math.sin(math.pi * t / 2)))
        x = max(0, min(x, width - 18))
        y = max(0, min(y, height - 12))
        annotations[str(frame_idx)] = [{"bbox": [x, y, 18, 12], "label": "drone"}]

    gt_path.write_text(json.dumps(annotations, indent=2), encoding="utf-8")

    return {"clip": "demo/demo.mp4", "ground_truth": "demo/demo_annotations.json"}

