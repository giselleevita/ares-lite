from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class FrameExtractionError(RuntimeError):
    pass


def _probe_video(clip_path: Path) -> tuple[int, float]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=nb_frames,r_frame_rate,duration",
        "-of",
        "json",
        str(clip_path),
    ]
    process = subprocess.run(cmd, capture_output=True, text=True)
    if process.returncode != 0:
        raise FrameExtractionError(f"ffprobe failed: {process.stderr.strip()}")

    payload = json.loads(process.stdout)
    streams = payload.get("streams", [])
    if not streams:
        raise FrameExtractionError("No video stream found")

    stream = streams[0]
    fps_raw = stream.get("r_frame_rate", "0/1")
    num, den = fps_raw.split("/")
    fps = float(num) / float(den) if float(den) else 0.0

    nb_frames = stream.get("nb_frames")
    if nb_frames and str(nb_frames).isdigit():
        total_frames = int(nb_frames)
    else:
        duration = float(stream.get("duration") or 0)
        total_frames = int(round(duration * fps))

    if total_frames <= 0:
        raise FrameExtractionError("Could not determine frame count")

    return total_frames, fps


def extract_sampled_frames(
    clip_path: Path,
    output_dir: Path,
    resize_width: int,
    every_n_frames: int,
    max_frames: int,
) -> tuple[list[int], float]:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise FrameExtractionError("ffmpeg/ffprobe not found on PATH")

    total_frames, fps = _probe_video(clip_path)
    sampled_frame_indices = list(range(0, total_frames, every_n_frames))[:max_frames]

    output_dir.mkdir(parents=True, exist_ok=True)

    for existing in output_dir.glob("frame_*.jpg"):
        existing.unlink()

    filter_expr = f"select='not(mod(n\\,{every_n_frames}))',scale={resize_width}:-2"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(clip_path),
        "-vf",
        filter_expr,
        "-vsync",
        "vfr",
        "-frames:v",
        str(len(sampled_frame_indices)),
        str(output_dir / "frame_%06d.jpg"),
    ]

    process = subprocess.run(cmd, capture_output=True, text=True)
    if process.returncode != 0:
        raise FrameExtractionError(f"ffmpeg frame extraction failed: {process.stderr.strip()}")

    extracted = sorted(output_dir.glob("frame_*.jpg"))
    if len(extracted) != len(sampled_frame_indices):
        raise FrameExtractionError(
            f"Extracted frame count mismatch: expected {len(sampled_frame_indices)}, got {len(extracted)}"
        )

    return sampled_frame_indices, fps
