#!/usr/bin/env python3
"""Generate lightweight offline demo clips and ground-truth annotations for ARES Lite."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

FPS = 15
DURATION_SEC = 8
WIDTH = 854
HEIGHT = 480
TOTAL_FRAMES = FPS * DURATION_SEC

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "backend" / "data"
CLIPS_DIR = DATA_DIR / "clips"
ANNOTATIONS_DIR = DATA_DIR / "annotations"


def clamp_xy(x: int, y: int, w: int, h: int) -> tuple[int, int]:
    return max(0, min(x, WIDTH - w)), max(0, min(y, HEIGHT - h))


def run_ffmpeg(args: list[str]) -> None:
    command = ["ffmpeg", "-y", *args]
    process = subprocess.run(command, capture_output=True, text=True)
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(command)}\n{process.stderr}")


def write_json(path: Path, payload: dict[str, list[dict[str, object]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def generate_clip_urban_dusk() -> None:
    output = CLIPS_DIR / "urban_dusk_demo.mp4"
    filter_complex = (
        "[0:v][1:v]overlay=x='40+87.5*t':y='240+60*sin(PI*t/2)'[moved];"
        "[moved]eq=gamma=0.82:brightness=-0.08:saturation=0.78,"
        "noise=alls=4:allf=t,"
        "format=yuv420p[out]"
    )

    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x101a2a:s={WIDTH}x{HEIGHT}:r={FPS}:d={DURATION_SEC}",
            "-f",
            "lavfi",
            "-i",
            f"color=c=white:s=26x16:r={FPS}:d={DURATION_SEC}",
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
            str(output),
        ]
    )

    annotations: dict[str, list[dict[str, object]]] = {}
    for frame_idx in range(TOTAL_FRAMES):
        t = frame_idx / FPS
        x = int(round(40 + 87.5 * t))
        y = int(round(240 + 60 * math.sin(math.pi * t / 2)))
        x, y = clamp_xy(x, y, 26, 16)
        annotations[str(frame_idx)] = [{"bbox": [x, y, 26, 16], "label": "drone"}]

    write_json(ANNOTATIONS_DIR / "urban_dusk_demo.json", annotations)


def generate_clip_forest_occlusion() -> None:
    output = CLIPS_DIR / "forest_occlusion_demo.mp4"
    filter_complex = (
        "[0:v][1:v]overlay=x='80+60*t':y='300-25*t'[ov1];"
        "[ov1][2:v]overlay=x='700-70*t':y='150+20*t'[ov2];"
        "[ov2]drawbox=x=260:y=0:w=90:h=480:color=black@0.45:t=fill,"
        "drawbox=x=520:y=0:w=70:h=480:color=black@0.35:t=fill,"
        "noise=alls=6:allf=t,"
        "eq=brightness=-0.03:contrast=0.9:saturation=0.7,"
        "format=yuv420p[out]"
    )

    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x1a2a18:s={WIDTH}x{HEIGHT}:r={FPS}:d={DURATION_SEC}",
            "-f",
            "lavfi",
            "-i",
            f"color=c=white:s=22x14:r={FPS}:d={DURATION_SEC}",
            "-f",
            "lavfi",
            "-i",
            f"color=c=white:s=20x12:r={FPS}:d={DURATION_SEC}",
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
            str(output),
        ]
    )

    annotations: dict[str, list[dict[str, object]]] = {}
    for frame_idx in range(TOTAL_FRAMES):
        t = frame_idx / FPS

        x1 = int(round(80 + 60 * t))
        y1 = int(round(300 - 25 * t))
        x1, y1 = clamp_xy(x1, y1, 22, 14)

        x2 = int(round(700 - 70 * t))
        y2 = int(round(150 + 20 * t))
        x2, y2 = clamp_xy(x2, y2, 20, 12)

        annotations[str(frame_idx)] = [
            {"bbox": [x1, y1, 22, 14], "label": "drone"},
            {"bbox": [x2, y2, 20, 12], "label": "drone"},
        ]

    write_json(ANNOTATIONS_DIR / "forest_occlusion_demo.json", annotations)


def generate_clip_clutter_false_positive() -> None:
    output = CLIPS_DIR / "clutter_false_positive.mp4"
    filter_graph = (
        "hue=s=0.25,"
        "eq=brightness=-0.12:contrast=0.82,"
        "noise=alls=22:allf=t+u,"
        "boxblur=1:1,"
        "format=yuv420p"
    )

    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={WIDTH}x{HEIGHT}:rate={FPS}:duration={DURATION_SEC}",
            "-vf",
            filter_graph,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "33",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )

    annotations: dict[str, list[dict[str, object]]] = {
        str(frame_idx): [] for frame_idx in range(TOTAL_FRAMES)
    }
    write_json(ANNOTATIONS_DIR / "clutter_false_positive.json", annotations)


def write_manifest() -> None:
    manifest = {
        "dataset_version": "phase2-v1",
        "fps": FPS,
        "duration_seconds": DURATION_SEC,
        "resolution": [WIDTH, HEIGHT],
        "assets": [
            {
                "scenario_id": "urban_dusk",
                "clip": "clips/urban_dusk_demo.mp4",
                "ground_truth": "annotations/urban_dusk_demo.json",
            },
            {
                "scenario_id": "forest_occlusion",
                "clip": "clips/forest_occlusion_demo.mp4",
                "ground_truth": "annotations/forest_occlusion_demo.json",
            },
            {
                "scenario_id": "clutter_false_positive",
                "clip": "clips/clutter_false_positive.mp4",
                "ground_truth": "annotations/clutter_false_positive.json",
            },
        ],
    }
    (DATA_DIR / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def main() -> None:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)

    generate_clip_urban_dusk()
    generate_clip_forest_occlusion()
    generate_clip_clutter_false_positive()
    write_manifest()

    print("Generated synthetic dataset assets:")
    print(f"- {CLIPS_DIR / 'urban_dusk_demo.mp4'}")
    print(f"- {CLIPS_DIR / 'forest_occlusion_demo.mp4'}")
    print(f"- {CLIPS_DIR / 'clutter_false_positive.mp4'}")
    print("Generated ground-truth JSON annotations in backend/data/annotations")


if __name__ == "__main__":
    main()
