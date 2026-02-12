from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.settings import settings
from db.models import Detection
from pipeline.frames import FrameExtractionError, extract_sampled_frames
from pipeline.inference import run_inference


def process_run(
    db: Session,
    run_id: str,
    scenario: dict[str, Any],
    options: dict[str, int],
) -> dict[str, Any]:
    clip_rel = scenario.get("clip")
    if not clip_rel:
        raise HTTPException(status_code=500, detail=f"Scenario {scenario.get('id')} has no clip configured")

    clip_path = Path(settings.data_dir) / clip_rel
    if not clip_path.exists():
        raise HTTPException(status_code=500, detail=f"Scenario clip not found: {clip_rel}")

    run_dir = Path(settings.runs_dir) / run_id
    frames_dir = run_dir / "frames"

    try:
        sampled_indices, fps = extract_sampled_frames(
            clip_path=clip_path,
            output_dir=frames_dir,
            resize_width=options["resize"],
            every_n_frames=options["every_n_frames"],
            max_frames=options["max_frames"],
        )
    except FrameExtractionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    frame_paths = sorted(frames_dir.glob("frame_*.jpg"))
    if len(frame_paths) != len(sampled_indices):
        raise HTTPException(
            status_code=500,
            detail=(
                "Frame extraction mismatch: "
                f"expected {len(sampled_indices)}, got {len(frame_paths)}"
            ),
        )

    detector_result = run_inference(frame_paths)
    if len(detector_result.frame_boxes) != len(sampled_indices):
        raise HTTPException(
            status_code=500,
            detail=(
                "Detection output mismatch: "
                f"expected {len(sampled_indices)}, got {len(detector_result.frame_boxes)}"
            ),
        )

    detections_to_write = [
        Detection(
            run_id=run_id,
            frame_idx=frame_idx,
            boxes_json=json.dumps(frame_boxes),
        )
        for frame_idx, frame_boxes in zip(sampled_indices, detector_result.frame_boxes)
    ]

    if detections_to_write:
        db.add_all(detections_to_write)

    run_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "run_id": run_id,
        "scenario_id": scenario.get("id"),
        "clip": clip_rel,
        "fps": fps,
        "frames_processed": len(sampled_indices),
        "frame_indices": sampled_indices,
        "detector_backend": detector_result.backend,
        "inference_seconds": detector_result.inference_seconds,
        "fallback_reason": detector_result.fallback_reason,
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "frames_processed": len(sampled_indices),
        "detections_written": len(sampled_indices),
        "fps": fps,
        "detector_backend": detector_result.backend,
        "inference_seconds": detector_result.inference_seconds,
        "fallback_reason": detector_result.fallback_reason,
    }
