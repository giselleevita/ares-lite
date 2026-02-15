from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.boxes import BoxValidationError, normalize_prediction_boxes
from core.cancel import CancelledRun
from core.gates import evaluate_gate, load_gates_config
from core.rng import choose_seed
from core.settings import settings
from db.models import Detection
from db.runs import is_cancel_requested, touch_run
from engagement.sim import simulate_engagement, upsert_engagement
from metrics.reliability import (
    compute_reliability_metrics,
    compute_baseline_key,
    find_baseline_metrics,
    load_ground_truth_annotations,
    upsert_metrics,
)
from metrics.readiness import compute_readiness, upsert_readiness
from pipeline.blindspots import get_reason_tags
from pipeline.frames import FrameExtractionError, extract_sampled_frames
from pipeline.inference import run_inference
from reporting.report import generate_run_report
from simulation.stressors import StressApplier, StressedFrame
from benchmarking.profiles import get_stress_profile


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

    if is_cancel_requested(db, run_id):
        raise CancelledRun("Cancelled")

    touch_run(db, run_id, stage="extracting_frames", progress=5, message="Extracting sampled frames")
    db.commit()

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

    # Benchmark-mode stress overrides (optional).
    stress_profile_id = str(options.get("stress_profile_id") or "scenario_default")
    if stress_profile_id and stress_profile_id != "scenario_default":
        profile = get_stress_profile(stress_profile_id)
        if profile is None:
            raise HTTPException(status_code=422, detail=f"Unknown stress_profile_id: {stress_profile_id}")
        # "none" is treated as baseline; enforce no stressors regardless of scenario config.
        scenario = {
            **scenario,
            "stressors": list(profile.get("stressors") or []),
            "params": dict(profile.get("params") or {}),
        }

    requested_seed_raw = options.get("seed")
    requested_seed = None if requested_seed_raw is None else int(requested_seed_raw)
    seed_used, deterministic = choose_seed(requested_seed)
    stress_enabled = not bool(options.get("disable_stress", False))
    persist_stressed_frames = bool(options.get("persist_stressed_frames", False))

    stressed_dir = run_dir / "stressed"
    stressed_dir.mkdir(parents=True, exist_ok=True)
    for existing in stressed_dir.glob("frame_*.jpg"):
        existing.unlink()

    if is_cancel_requested(db, run_id):
        raise CancelledRun("Cancelled")

    touch_run(db, run_id, stage="stressing_frames", progress=15, message="Applying stressors")
    db.commit()

    applier: StressApplier | None = None
    if stress_enabled:
        applier = StressApplier(scenario_config=scenario, seed=seed_used)

    inference_frame_paths: list[Path] = []
    inference_frame_indices: list[int] = []

    total = max(1, len(sampled_indices))
    cancel_every = int(getattr(settings, "cancel_check_every_n_frames", 10) or 10)
    cancel_every = max(1, cancel_every)
    for sequence_idx, (frame_idx, frame_path) in enumerate(zip(sampled_indices, frame_paths)):
        if sequence_idx % cancel_every == 0 and is_cancel_requested(db, run_id):
            raise CancelledRun("Cancelled")

        image = cv2.imread(str(frame_path))
        if image is None:
            raise HTTPException(status_code=500, detail=f"Failed to load extracted frame: {frame_path.name}")

        if applier is not None:
            stressed = applier.apply(frame_idx=int(frame_idx), image=image, sequence_idx=sequence_idx)
        else:
            stressed = StressedFrame(frame_idx=int(frame_idx), image=image.copy())

        output_path = stressed_dir / f"frame_{int(frame_idx):06d}.jpg"
        if not cv2.imwrite(str(output_path), stressed.image):
            raise HTTPException(status_code=500, detail=f"Failed to write stressed frame: {output_path.name}")
        if not stressed.dropped:
            inference_frame_paths.append(output_path)
            inference_frame_indices.append(int(frame_idx))

        if sequence_idx % 20 == 0 or sequence_idx == total - 1:
            # 15..40%
            progress = 15 + int(((sequence_idx + 1) / total) * 25)
            touch_run(
                db,
                run_id,
                stage="stressing_frames",
                progress=progress,
                message=f"Prepared {sequence_idx + 1}/{total} stressed frames",
            )
            db.commit()

    if applier is not None:
        stress_meta = applier.meta()
    else:
        stress_meta = {
            "seed": seed_used,
            "stressors_applied": [],
            "stress_enabled": False,
            "frame_drop": {"enabled": False, "keep_every": 1, "dropped_indices": []},
        }

    if is_cancel_requested(db, run_id):
        raise CancelledRun("Cancelled")

    touch_run(db, run_id, stage="inference", progress=45, message="Running detector inference")
    db.commit()

    detector_result = run_inference(inference_frame_paths)
    if len(detector_result.frame_boxes) != len(inference_frame_indices):
        raise HTTPException(
            status_code=500,
            detail=(
                "Detection output mismatch after stress pipeline: "
                f"expected {len(inference_frame_indices)}, got {len(detector_result.frame_boxes)}"
            ),
        )

    # Normalize predictions before persisting/metrics so schema errors become clear failures.
    detections_by_frame: dict[int, list[dict[str, Any]]] = {frame_idx: [] for frame_idx in sampled_indices}
    for frame_idx, boxes in zip(inference_frame_indices, detector_result.frame_boxes):
        try:
            detections_by_frame[int(frame_idx)] = normalize_prediction_boxes(boxes, context=f"pred frame {frame_idx}")
        except BoxValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if is_cancel_requested(db, run_id):
        raise CancelledRun("Cancelled")

    touch_run(db, run_id, stage="persisting", progress=70, message="Persisting detections")
    db.commit()

    # Idempotency: if a run is retried/recovered, avoid duplicating detections.
    db.query(Detection).filter(Detection.run_id == run_id).delete()

    batch: list[Detection] = []
    for idx, frame_idx in enumerate(sampled_indices):
        batch.append(
            Detection(
                run_id=run_id,
                frame_idx=int(frame_idx),
                boxes_json=json.dumps(detections_by_frame.get(int(frame_idx), []), ensure_ascii=True),
            )
        )
        if len(batch) >= 200:
            db.add_all(batch)
            db.flush()
            batch = []
            touch_run(
                db,
                run_id,
                stage="persisting",
                progress=70 + int(((idx + 1) / max(1, len(sampled_indices))) * 5),
                message=f"Persisted {idx + 1}/{len(sampled_indices)} frames",
            )
            db.commit()

    if batch:
        db.add_all(batch)
        db.flush()
    db.commit()

    if is_cancel_requested(db, run_id):
        raise CancelledRun("Cancelled")

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

    baseline_key = compute_baseline_key(
        video_id=str(scenario_snapshot["video_id"]),
        detector_backend=detector_result.backend,
        options=options,
    )

    config_envelope = {
        "options": options,
        "requested_seed": requested_seed,
        "seed_used": seed_used,
        "deterministic": deterministic,
        "stress_enabled": stress_enabled and bool(scenario_snapshot["stressors"]),
        "stress_profile_id": stress_profile_id,
        "scenario_snapshot": scenario_snapshot,
        "video_id": scenario_snapshot["video_id"],
        "difficulty": scenario_snapshot["difficulty"],
        "detector_backend": detector_result.backend,
        "baseline_key": baseline_key,
        "persist_stressed_frames": persist_stressed_frames,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    annotation_rel = scenario.get("ground_truth")
    annotation_path = Path(settings.data_dir) / annotation_rel if annotation_rel else Path("")
    try:
        ground_truth_by_frame = load_ground_truth_annotations(annotation_path, sampled_indices)
    except BoxValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if is_cancel_requested(db, run_id):
        raise CancelledRun("Cancelled")

    touch_run(db, run_id, stage="metrics", progress=80, message="Computing reliability metrics")
    db.commit()

    baseline_run_id, baseline_metrics = find_baseline_metrics(db=db, current_run_id=run_id, baseline_key=baseline_key)
    baseline_missing = baseline_run_id is None or baseline_metrics is None

    try:
        reliability_payload = compute_reliability_metrics(
            detections_by_frame=detections_by_frame,
            ground_truth_by_frame=ground_truth_by_frame,
            frame_indices=sampled_indices,
            fps=fps,
            iou_threshold=0.3,
            baseline_metrics=baseline_metrics,
            baseline_run_id=baseline_run_id,
            baseline_missing=baseline_missing,
            baseline_key=baseline_key,
        )
    except BoxValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    upsert_metrics(db=db, run_id=run_id, metrics_payload=reliability_payload)

    engagement_payload = simulate_engagement(
        frame_summaries=reliability_payload.get("frame_summaries", []),
        detections_by_frame=detections_by_frame,
        difficulty=float(scenario_snapshot.get("difficulty", 0.5)),
        threshold=0.55,
    )
    upsert_engagement(db=db, run_id=run_id, engagement_payload=engagement_payload)

    readiness_payload = compute_readiness(
        metrics_payload=reliability_payload,
        engagement_payload=engagement_payload,
        stress_enabled=bool(config_envelope.get("stress_enabled", False)),
    )
    upsert_readiness(db=db, run_id=run_id, readiness_payload=readiness_payload)

    gates_config = load_gates_config()
    gate_payload = evaluate_gate(
        run={"id": run_id, "scenario_id": str(scenario.get("id")), "status": "processing"},
        metrics=reliability_payload,
        readiness=readiness_payload,
        engagement=engagement_payload,
        baseline_missing=baseline_missing,
        gates_config=gates_config,
    )

    db.commit()

    if is_cancel_requested(db, run_id):
        raise CancelledRun("Cancelled")

    false_negative_frames = reliability_payload.get("false_negative_frames", {}).get("frames", [])
    blindspots: list[dict[str, Any]] = []
    for frame_idx in false_negative_frames:
        idx = int(frame_idx)
        reason_tags = get_reason_tags(
            frame_idx=idx,
            gt_boxes=ground_truth_by_frame.get(idx, []),
            stressors=scenario_snapshot.get("stressors", []),
        )
        blindspots.append({"frame_idx": idx, "reason_tags": reason_tags})

    touch_run(db, run_id, stage="reporting", progress=95, message="Generating report")
    db.commit()

    if is_cancel_requested(db, run_id):
        raise CancelledRun("Cancelled")

    report_paths = generate_run_report(
        run_id=run_id,
        scenario_id=str(scenario.get("id")),
        config_envelope=config_envelope,
        detector_backend=detector_result.backend,
        fallback_reason=detector_result.fallback_reason,
        metrics_payload=reliability_payload,
        engagement_payload=engagement_payload,
        readiness_payload=readiness_payload,
        gate_payload=gate_payload,
        blindspots=blindspots,
        ground_truth_by_frame=ground_truth_by_frame,
        detections_by_frame=detections_by_frame,
        run_dir=run_dir,
    )

    # If callers don't want stressed frames persisted, remove them after report generation.
    if not persist_stressed_frames:
        stressed_dir = run_dir / "stressed"
        for existing in stressed_dir.glob("frame_*.jpg"):
            try:
                existing.unlink()
            except Exception:
                # Best-effort cleanup only.
                pass

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
        "reliability_metrics": reliability_payload,
        "baseline_key": baseline_key,
        "baseline_matched_run_id": baseline_run_id,
        "gate": gate_payload,
        "gates_config_snapshot": gates_config,
        "engagement": engagement_payload,
        "readiness": readiness_payload,
        "blindspots": blindspots,
        "report_paths": report_paths,
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
        "reliability_metrics": reliability_payload,
        "engagement": engagement_payload,
        "readiness": readiness_payload,
        "blindspots": blindspots,
        "report_paths": report_paths,
        "detector_backend": detector_result.backend,
        "inference_seconds": detector_result.inference_seconds,
        "fallback_reason": detector_result.fallback_reason,
    }
