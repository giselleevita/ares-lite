from __future__ import annotations

import shutil

import pytest

from pipeline.demo_assets import ensure_golden_demo_assets


def test_demo_assets_generation(tmp_path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe unavailable in environment")

    mapping = ensure_golden_demo_assets(tmp_path)
    assert mapping["clip"] == "demo/demo.mp4"
    assert mapping["ground_truth"] == "demo/demo_annotations.json"

    clip_path = tmp_path / "demo" / "demo.mp4"
    gt_path = tmp_path / "demo" / "demo_annotations.json"
    assert clip_path.exists()
    assert gt_path.exists()

