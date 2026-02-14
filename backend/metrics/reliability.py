from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db.models import Metric, Run
from core.boxes import BoxValidationError, normalize_bbox_xywh, normalize_ground_truth_boxes, normalize_prediction_boxes


def iou(box_a: list[float], box_b: list[float]) -> float:
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b

    a_x2 = ax + aw
    a_y2 = ay + ah
    b_x2 = bx + bw
    b_y2 = by + bh

    inter_x1 = max(ax, bx)
    inter_y1 = max(ay, by)
    inter_x2 = min(a_x2, b_x2)
    inter_y2 = min(a_y2, b_y2)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0

    area_a = max(0.0, aw) * max(0.0, ah)
    area_b = max(0.0, bw) * max(0.0, bh)
    union = area_a + area_b - inter_area
    if union <= 0:
        return 0.0
    return inter_area / union


def _match_frame(
    predictions: list[dict[str, Any]],
    ground_truth: list[dict[str, Any]],
    iou_threshold: float,
) -> dict[str, Any]:
    # Normalize/validate boxes up-front so metric computation doesn't crash with cryptic errors.
    try:
        predictions_norm = normalize_prediction_boxes(predictions, context="metrics:predictions")
        ground_truth_norm = normalize_ground_truth_boxes(ground_truth, context="metrics:ground_truth")
    except BoxValidationError as exc:
        raise BoxValidationError(f"Invalid boxes while computing metrics: {exc}") from exc

    candidate_pairs: list[tuple[float, int, int]] = []
    for pred_idx, pred in enumerate(predictions_norm):
        pred_bbox = normalize_bbox_xywh(pred.get("bbox"), context=f"metrics:pred[{pred_idx}].bbox")
        for gt_idx, gt in enumerate(ground_truth_norm):
            gt_bbox = normalize_bbox_xywh(gt.get("bbox"), context=f"metrics:gt[{gt_idx}].bbox")
            score = iou(pred_bbox, gt_bbox)
            if score >= iou_threshold:
                candidate_pairs.append((score, pred_idx, gt_idx))

    candidate_pairs.sort(reverse=True, key=lambda item: item[0])

    matched_pred: set[int] = set()
    matched_gt: set[int] = set()
    matches: list[dict[str, Any]] = []

    for score, pred_idx, gt_idx in candidate_pairs:
        if pred_idx in matched_pred or gt_idx in matched_gt:
            continue
        matched_pred.add(pred_idx)
        matched_gt.add(gt_idx)
        matches.append({"pred_idx": pred_idx, "gt_idx": gt_idx, "iou": round(score, 4)})

    tp = len(matches)
    fp = max(0, len(predictions) - tp)
    fn = max(0, len(ground_truth) - tp)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "has_tp": tp > 0,
        "matches": matches,
        "matched_gt_indices": sorted(matched_gt),
    }


def compute_reliability_metrics(
    detections_by_frame: dict[int, list[dict[str, Any]]],
    ground_truth_by_frame: dict[int, list[dict[str, Any]]],
    frame_indices: list[int],
    fps: float,
    iou_threshold: float = 0.3,
    baseline_metrics: dict[str, Any] | None = None,
    baseline_run_id: str | None = None,
    baseline_missing: bool = False,
    baseline_key: str | None = None,
) -> dict[str, Any]:
    total_tp = 0
    total_fp = 0
    total_fn = 0

    false_negative_frames: list[int] = []
    frame_summaries: list[dict[str, Any]] = []
    gt_presence_frames: list[int] = []
    tp_presence_frames: list[int] = []

    for frame_idx in frame_indices:
        gt_boxes = ground_truth_by_frame.get(frame_idx, [])
        pred_boxes = detections_by_frame.get(frame_idx, [])
        try:
            frame_match = _match_frame(pred_boxes, gt_boxes, iou_threshold=iou_threshold)
        except BoxValidationError as exc:
            raise BoxValidationError(f"frame_idx={frame_idx}: {exc}") from exc

        total_tp += frame_match["tp"]
        total_fp += frame_match["fp"]
        total_fn += frame_match["fn"]

        if gt_boxes:
            gt_presence_frames.append(frame_idx)
            if frame_match["has_tp"]:
                tp_presence_frames.append(frame_idx)
            else:
                false_negative_frames.append(frame_idx)

        frame_summaries.append(
            {
                "frame_idx": frame_idx,
                "gt_count": len(gt_boxes),
                "prediction_count": len(pred_boxes),
                "tp": frame_match["tp"],
                "fp": frame_match["fp"],
                "fn": frame_match["fn"],
                "has_tp": frame_match["has_tp"],
                "matched_gt_indices": frame_match["matched_gt_indices"],
            }
        )

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0

    duration_minutes = (len(frame_indices) / fps) / 60.0 if fps > 0 else 0.0
    fp_rate_per_minute = total_fp / duration_minutes if duration_minutes > 0 else 0.0

    first_tp_frame = min(tp_presence_frames) if tp_presence_frames else None
    detection_delay_seconds = (first_tp_frame / fps) if first_tp_frame is not None and fps > 0 else None

    longest_streak = 0
    current_streak = 0
    gt_frame_set = set(gt_presence_frames)
    tp_frame_set = set(tp_presence_frames)
    for frame_idx in frame_indices:
        if frame_idx not in gt_frame_set:
            continue
        if frame_idx in tp_frame_set:
            current_streak += 1
            longest_streak = max(longest_streak, current_streak)
        else:
            current_streak = 0

    total_gt_frames = len(gt_presence_frames)
    track_stability_index = longest_streak / total_gt_frames if total_gt_frames else 0.0

    degradation_delta: dict[str, Any] | None = None
    if baseline_metrics:
        degradation_delta = {
            "baseline_run_id": baseline_run_id,
            "precision_delta": round(precision - float(baseline_metrics.get("precision", 0.0)), 4),
            "recall_delta": round(recall - float(baseline_metrics.get("recall", 0.0)), 4),
            "stability_delta": round(
                track_stability_index - float(baseline_metrics.get("track_stability_index", 0.0)),
                4,
            ),
            "fp_rate_per_minute_delta": round(
                fp_rate_per_minute - float(baseline_metrics.get("false_positive_rate_per_minute", 0.0)),
                4,
            ),
            "detection_delay_seconds_delta": round(
                (detection_delay_seconds or 0.0) - float(baseline_metrics.get("detection_delay_seconds") or 0.0),
                4,
            ),
        }

    return {
        "baseline_key": baseline_key,
        "baseline_missing": bool(baseline_missing),
        "baseline_matched_run_id": baseline_run_id,
        "iou_threshold": iou_threshold,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "false_positive_rate_per_minute": round(fp_rate_per_minute, 4),
        "false_negative_frames": {
            "count": len(false_negative_frames),
            "frames": false_negative_frames,
        },
        "detection_delay_seconds": None if detection_delay_seconds is None else round(detection_delay_seconds, 4),
        "track_stability_index": round(track_stability_index, 4),
        "counts": {
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            "gt_frames": total_gt_frames,
            "frames_evaluated": len(frame_indices),
        },
        "frame_summaries": frame_summaries,
        "degradation_delta": degradation_delta,
    }


def upsert_metrics(db: Any, run_id: str, metrics_payload: dict[str, Any]) -> None:
    existing = db.query(Metric).filter(Metric.run_id == run_id).first()
    if existing is None:
        existing = Metric(run_id=run_id, metrics_json=json.dumps(metrics_payload))
    else:
        existing.metrics_json = json.dumps(metrics_payload)
    db.add(existing)


def _extract_options(config_payload: dict[str, Any]) -> dict[str, Any]:
    if "options" in config_payload and isinstance(config_payload["options"], dict):
        return config_payload["options"]
    # Backward compatibility for older runs.
    if {"resize", "every_n_frames", "max_frames"} <= set(config_payload.keys()):
        return config_payload
    return {}


def compute_baseline_key(
    *,
    video_id: str,
    detector_backend: str,
    options: dict[str, Any],
) -> str:
    return "|".join(
        [
            str(video_id),
            str(detector_backend),
            str(int(options.get("resize", 0))),
            str(int(options.get("every_n_frames", 0))),
            str(int(options.get("max_frames", 0))),
        ]
    )


def find_baseline_metrics(
    db: Any,
    current_run_id: str,
    baseline_key: str,
) -> tuple[str | None, dict[str, Any] | None]:
    candidates = (
        db.query(Run)
        .filter(Run.id != current_run_id)
        .filter(Run.status == "completed")
        .order_by(Run.created_at.desc())
        .all()
    )

    for run in candidates:
        try:
            config_payload = json.loads(run.config_json)
        except Exception:
            continue

        candidate_stress_enabled = bool(config_payload.get("stress_enabled", True))
        if candidate_stress_enabled:
            continue

        candidate_baseline_key = config_payload.get("baseline_key")
        if not candidate_baseline_key:
            # Back-compat for older runs: compute from legacy fields.
            candidate_video_id = str(config_payload.get("video_id", ""))
            candidate_backend = str(config_payload.get("detector_backend", ""))
            candidate_options = _extract_options(config_payload)
            candidate_baseline_key = compute_baseline_key(
                video_id=candidate_video_id,
                detector_backend=candidate_backend,
                options=candidate_options,
            )

        if str(candidate_baseline_key) != str(baseline_key):
            continue

        metric_row = db.query(Metric).filter(Metric.run_id == run.id).first()
        if metric_row is None:
            continue
        try:
            return run.id, json.loads(metric_row.metrics_json)
        except Exception:
            continue

    return None, None


def load_ground_truth_annotations(annotation_path: Path, frame_indices: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not annotation_path.exists():
        return {frame_idx: [] for frame_idx in frame_indices}

    try:
        payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BoxValidationError(f"Invalid annotation JSON: {annotation_path.name}: {exc}") from exc

    if not isinstance(payload, dict):
        raise BoxValidationError(f"Invalid annotation JSON: {annotation_path.name}: expected object at top-level")

    ground_truth: dict[int, list[dict[str, Any]]] = {}
    for frame_idx in frame_indices:
        raw = payload.get(str(frame_idx), [])
        ground_truth[frame_idx] = normalize_ground_truth_boxes(raw, context=f"gt frame {frame_idx}")
    return ground_truth
