from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class BoxValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ImageSize:
    width: int
    height: int


def normalize_bbox_xywh(
    raw: Any,
    *,
    context: str,
    image_size: ImageSize | None = None,
) -> list[int]:
    """Return bbox as [x, y, w, h] ints. Raises BoxValidationError on invalid input."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise BoxValidationError(f"{context}: bbox must be a list of 4 numbers [x,y,w,h]")

    try:
        x_f, y_f, w_f, h_f = (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    except Exception as exc:  # pragma: no cover
        raise BoxValidationError(f"{context}: bbox values must be numeric") from exc

    # Reject NaN/inf explicitly to avoid surprising downstream behavior.
    for name, value in (("x", x_f), ("y", y_f), ("w", w_f), ("h", h_f)):
        if value != value:  # NaN
            raise BoxValidationError(f"{context}: bbox {name} must be a real number")
        if value in (float("inf"), float("-inf")):
            raise BoxValidationError(f"{context}: bbox {name} must be finite")

    if not (w_f > 0 and h_f > 0):
        raise BoxValidationError(f"{context}: bbox w/h must be > 0")

    x = int(round(x_f))
    y = int(round(y_f))
    w = int(round(w_f))
    h = int(round(h_f))

    # Enforce minimum extents.
    w = max(1, w)
    h = max(1, h)

    # Always clamp origin to non-negative space.
    x = max(0, x)
    y = max(0, y)

    if image_size is not None:
        x = max(0, min(x, image_size.width - 1))
        y = max(0, min(y, image_size.height - 1))
        # Clamp w/h so the box remains inside the image.
        w = max(1, min(w, image_size.width - x))
        h = max(1, min(h, image_size.height - y))

    return [x, y, w, h]


def normalize_confidence(raw: Any, *, context: str) -> float:
    try:
        value = float(raw)
    except Exception as exc:  # pragma: no cover
        raise BoxValidationError(f"{context}: confidence must be numeric") from exc

    if value != value:  # NaN
        raise BoxValidationError(f"{context}: confidence must be a real number")
    return max(0.0, min(1.0, value))


def normalize_prediction_boxes(
    boxes: Any,
    *,
    context: str,
    image_size: ImageSize | None = None,
) -> list[dict[str, Any]]:
    if boxes is None:
        return []
    if not isinstance(boxes, list):
        raise BoxValidationError(f"{context}: predicted boxes must be a list")

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(boxes):
        if not isinstance(item, dict):
            raise BoxValidationError(f"{context}: box[{idx}] must be an object")

        bbox = normalize_bbox_xywh(item.get("bbox"), context=f"{context}: box[{idx}].bbox", image_size=image_size)
        confidence = normalize_confidence(item.get("confidence", 0.0), context=f"{context}: box[{idx}].confidence")
        label = str(item.get("label", "unknown"))

        out = dict(item)
        out["bbox"] = bbox
        out["confidence"] = round(confidence, 4)
        out["label"] = label
        normalized.append(out)

    return normalized


def normalize_ground_truth_boxes(
    boxes: Any,
    *,
    context: str,
    image_size: ImageSize | None = None,
) -> list[dict[str, Any]]:
    if boxes is None:
        return []
    if not isinstance(boxes, list):
        raise BoxValidationError(f"{context}: ground truth must be a list")

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(boxes):
        if not isinstance(item, dict):
            raise BoxValidationError(f"{context}: gt[{idx}] must be an object")
        bbox = normalize_bbox_xywh(item.get("bbox"), context=f"{context}: gt[{idx}].bbox", image_size=image_size)
        label = str(item.get("label", "drone"))
        out = dict(item)
        out["bbox"] = bbox
        out["label"] = label
        normalized.append(out)

    return normalized
