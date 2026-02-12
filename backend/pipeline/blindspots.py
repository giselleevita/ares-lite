from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2

from db.models import Detection


def load_ground_truth_map(annotation_path: Path) -> dict[str, list[dict[str, Any]]]:
    if not annotation_path.exists():
        return {}
    try:
        payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def get_reason_tags(
    frame_idx: int,
    gt_boxes: list[dict[str, Any]],
    stressors: list[str],
) -> list[str]:
    tags: list[str] = []
    stressor_set = set(stressors)

    if "occlusion_rectangles" in stressor_set:
        tags.append("occlusion")
    if {"low_light", "fog"} & stressor_set:
        tags.append("low_light")

    small_object = False
    if gt_boxes:
        avg_area = sum((box["bbox"][2] * box["bbox"][3]) for box in gt_boxes if "bbox" in box) / max(1, len(gt_boxes))
        small_object = avg_area < 900
    if small_object:
        tags.append("small_object")

    if not tags:
        tags.append("detection_miss")
    return sorted(set(tags))


def get_detection_boxes(db: Any, run_id: str, frame_idx: int) -> list[dict[str, Any]]:
    row = (
        db.query(Detection)
        .filter(Detection.run_id == run_id)
        .filter(Detection.frame_idx == frame_idx)
        .first()
    )
    if row is None:
        return []
    try:
        payload = json.loads(row.boxes_json)
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def render_overlay(
    frame_path: Path,
    ground_truth_boxes: list[dict[str, Any]],
    prediction_boxes: list[dict[str, Any]],
) -> bytes:
    frame = cv2.imread(str(frame_path))
    if frame is None:
        raise RuntimeError(f"Unable to read frame: {frame_path}")

    for gt in ground_truth_boxes:
        x, y, w, h = [int(v) for v in gt.get("bbox", [0, 0, 0, 0])]
        cv2.rectangle(frame, (x, y), (x + w, y + h), (34, 197, 94), 2)
        cv2.putText(frame, "GT", (x, max(16, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (34, 197, 94), 1, cv2.LINE_AA)

    for pred in prediction_boxes:
        x, y, w, h = [int(v) for v in pred.get("bbox", [0, 0, 0, 0])]
        conf = float(pred.get("confidence", 0.0))
        label = f"PRED {conf:.2f}"
        cv2.rectangle(frame, (x, y), (x + w, y + h), (239, 68, 68), 2)
        cv2.putText(frame, label, (x, max(16, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (239, 68, 68), 1, cv2.LINE_AA)

    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("Failed to encode overlay image")
    return encoded.tobytes()
