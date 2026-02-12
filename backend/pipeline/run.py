from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.settings import settings
from db.models import Detection
from pipeline.frames import FrameExtractionError, extract_sampled_frames
from pipeline.inference import run_inference
from simulation.stressors import FrameRecord, StressedFrame, apply_stress_pipeline


def process_run(
    db: Session,
    run_id: str,
    scenario: dict[str, Any],
    options: dict[str, Any],
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

    raw_frames: list[FrameRecord] = []
    for frame_idx, frame_path in zip(sampled_indices, frame_paths):
        image = cv2.imread(str(frame_path))
        if image is None:
            raise HTTPException(status_code=500, detail=f"Failed to load extracted frame: {frame_path.name}")
        raw_frames.append(FrameRecord(frame_idx=frame_idx, image=image))

    seed_used = int(options.get("seed", scenario.get("default_seed", 1337)))
    stress_enabled = not bool(options.get("disable_stress", False))
    if stress_enabled:
        stressed_frames, stress_meta = apply_stress_pipeline(
            frames=raw_frames,
            scenario_config=scenario,
            seed=seed_used,
        )
    else:
        stressed_frames = [StressedFrame(frame_idx=frame.frame_idx, image=frame.image.copy()) for frame in raw_frames]
        stress_meta = {
            "seed": seed_used,
            "stressors_applied": [],
            "stress_enabled": False,
            "frame_drop": {
                "enabled": False,
                "keep_every": 1,
                "dropped_indices": [],
            },
        }

    stressed_dir = run_dir / "stressed"
    stressed_dir.mkdir(parents=True, exist_ok=True)
    for existing in stressed_dir.glob("frame_*.jpg"):
        existing.unlink()

    inference_frame_paths: list[Path] = []
    inference_frame_indices: list[int] = []
    for stressed in stressed_frames:
        output_path = stressed_dir / f"frame_{stressed.frame_idx:06d}.jpg"
        if not cv2.imwrite(str(output_path), stressed.image):
            raise HTTPException(status_code=500, detail=f"Failed to write stressed frame: {output_path.name}")
        if not stressed.dropped:
            inference_frame_paths.append(output_path)
            inference_frame_indices.append(stressed.frame_idx)

    detector_result = run_inference(inference_frame_paths)
    if len(detector_result.frame_boxes) != len(inference_frame_indices):
        raise HTTPException(
            status_code=500,
            detail=(
                "Detection output mismatch after stress pipeline: "
                f"expected {len(inference_frame_indices)}, got {len(detector_result.frame_boxes)}"
            ),
        )

    detections_by_frame: dict[int, list[dict[str, Any]]] = {frame_idx: [] for frame_idx in sampled_indices}
    for frame_idx, boxes in zip(inference_frame_indices, detector_result.frame_boxes):
        detections_by_frame[frame_idx] = boxes

    detections_to_write = [
        Detection(
            run_id=run_id,
            frame_idx=frame_idx,
            boxes_json=json.dumps(detections_by_frame.get(frame_idx, [])),
        )
        for frame_idx in sampled_indices
    ]

    if detections_to_write:
        db.add_all(detections_to_write)

    scenario_snapshot = {
        "id": scenario.get("id"),
        "name": scenario.get("name"),
        "description": scenario.get("description"),
        "clip": scenario.get("clip"),
        "ground_truth": scenario.get("ground_truth"),
        "video_id": scenario.get("video_id", scenario.get("clip")),
        "difficulty": scenario.get("difficulty", 0.5),
        "stressors": scenario.get("stressors", []),
        "params": scenario.get("params", {}),
        "default_seed": scenario.get("default_seed", 1337),
    }

    config_envelope = {
        "options": options,
        "seed_used": seed_used,
        "stress_enabled": stress_enabled and bool(scenario_snapshot["stressors"]),
        "scenario_snapshot": scenario_snapshot,
        "video_id": scenario_snapshot["video_id"],
        "difficulty": scenario_snapshot["difficulty"],
        "detector_backend": detector_result.backend,
    }

    run_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "run_id": run_id,
        "scenario_id": scenario.get("id"),
        "clip": clip_rel,
        "fps": fps,
        "frames_processed": len(sampled_indices),
        "frame_indices": sampled_indices,
        "stressed_frame_indices": inference_frame_indices,
        "dropped_frame_indices": stress_meta.get("frame_drop", {}).get("dropped_indices", []),
        "detector_backend": detector_result.backend,
        "inference_seconds": detector_result.inference_seconds,
        "fallback_reason": detector_result.fallback_reason,
        "stress": stress_meta,
        "config_envelope": config_envelope,
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "frames_processed": len(sampled_indices),
        "detections_written": len(sampled_indices),
        "fps": fps,
        "seed_used": seed_used,
        "stress_meta": stress_meta,
        "scenario_snapshot": scenario_snapshot,
        "config_envelope": config_envelope,
        "detector_backend": detector_result.backend,
        "inference_seconds": detector_result.inference_seconds,
        "fallback_reason": detector_result.fallback_reason,
    }
