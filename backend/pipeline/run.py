from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.settings import settings
from db.models import Detection
from pipeline.frames import FrameExtractionError, extract_sampled_frames


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

    if sampled_indices:
        db.add_all(
            [
                Detection(run_id=run_id, frame_idx=frame_idx, boxes_json="[]")
                for frame_idx in sampled_indices
            ]
        )

    run_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "run_id": run_id,
        "scenario_id": scenario.get("id"),
        "clip": clip_rel,
        "fps": fps,
        "frames_processed": len(sampled_indices),
        "frame_indices": sampled_indices,
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "frames_processed": len(sampled_indices),
        "detections_written": len(sampled_indices),
        "fps": fps,
    }
