from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import cv2

from core.settings import settings

logger = logging.getLogger(__name__)


class DetectorError(RuntimeError):
    pass


class DetectorTimeoutError(DetectorError):
    pass


@dataclass
class DetectorResult:
    backend: str
    frame_boxes: list[list[dict[str, Any]]]
    inference_seconds: float
    fallback_reason: str | None = None


class MotionDetector:
    def __init__(self, min_area: int = 20, max_boxes: int = 8) -> None:
        self.min_area = min_area
        self.max_boxes = max_boxes

    def _contours_to_boxes(
        self,
        binary_mask: Any,
        frame_shape: tuple[int, int, int],
        label: str,
        source: str,
        floor_scale: float,
    ) -> list[dict[str, Any]]:
        contour_result = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = contour_result[0] if len(contour_result) == 2 else contour_result[1]

        frame_area = frame_shape[0] * frame_shape[1]
        area_floor = max(self.min_area, int(frame_area * floor_scale))

        boxes: list[dict[str, Any]] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < area_floor:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            if w <= 1 or h <= 1:
                continue

            confidence = min(0.95, max(0.2, area / frame_area * 70.0))
            boxes.append(
                {
                    "bbox": [int(x), int(y), int(w), int(h)],
                    "confidence": round(float(confidence), 4),
                    "label": label,
                    "source": source,
                }
            )

        return sorted(
            boxes,
            key=lambda item: item["bbox"][2] * item["bbox"][3],
            reverse=True,
        )[: self.max_boxes]

    def _bright_fallback_boxes(self, gray: Any, frame_shape: tuple[int, int, int]) -> list[dict[str, Any]]:
        _, bright = cv2.threshold(gray, 205, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, kernel, iterations=1)
        return self._contours_to_boxes(
            binary_mask=bright,
            frame_shape=frame_shape,
            label="moving_object",
            source="motion_bright",
            floor_scale=0.00003,
        )

    def detect(self, frame_paths: list[Path], _: float = 0.0) -> list[list[dict[str, Any]]]:
        detections: list[list[dict[str, Any]]] = []
        previous_gray: Any | None = None

        for frame_path in frame_paths:
            frame = cv2.imread(str(frame_path))
            if frame is None:
                detections.append([])
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)

            motion_boxes: list[dict[str, Any]] = []
            if previous_gray is not None:
                diff = cv2.absdiff(previous_gray, gray)
                _, threshold = cv2.threshold(diff, 8, 255, cv2.THRESH_BINARY)
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
                threshold = cv2.dilate(threshold, kernel, iterations=2)
                motion_boxes = self._contours_to_boxes(
                    binary_mask=threshold,
                    frame_shape=frame.shape,
                    label="moving_object",
                    source="motion_diff",
                    floor_scale=0.00002,
                )

            if not motion_boxes:
                motion_boxes = self._bright_fallback_boxes(gray=gray, frame_shape=frame.shape)

            detections.append(motion_boxes)
            previous_gray = gray

        return detections


class YOLODetector:
    TARGET_KEYWORDS = ("drone", "uav", "bird", "airplane", "kite", "helicopter")

    def __init__(self, model_path: str, conf_threshold: float = 0.25) -> None:
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise DetectorError(f"ultralytics unavailable: {exc}") from exc

        self.conf_threshold = conf_threshold
        self.model_path = model_path
        try:
            self.model = YOLO(self.model_path)
        except Exception as exc:  # pragma: no cover
            raise DetectorError(f"failed to load YOLO model '{self.model_path}': {exc}") from exc

    def _normalize_label(self, class_name: str) -> str:
        normalized = class_name.lower()
        if "drone" in normalized or "uav" in normalized:
            return "drone"
        if any(keyword in normalized for keyword in ("bird", "airplane", "kite", "helicopter")):
            return "drone_proxy"
        return "drone_proxy"

    def detect(self, frame_paths: list[Path], time_budget_sec: float) -> list[list[dict[str, Any]]]:
        start = time.monotonic()
        all_detections: list[list[dict[str, Any]]] = []

        for frame_path in frame_paths:
            if time.monotonic() - start > time_budget_sec:
                raise DetectorTimeoutError(
                    f"YOLO inference exceeded {time_budget_sec:.1f}s budget"
                )

            try:
                results = self.model.predict(
                    source=str(frame_path),
                    conf=self.conf_threshold,
                    imgsz=640,
                    device="cpu",
                    verbose=False,
                )
            except Exception as exc:  # pragma: no cover
                raise DetectorError(f"YOLO inference failed: {exc}") from exc

            result = results[0]
            names = result.names
            chosen_boxes: list[dict[str, Any]] = []
            any_boxes: list[dict[str, Any]] = []

            for box in result.boxes:
                cls_id = int(box.cls.item())
                class_name = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else names[cls_id]
                x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                bbox = [
                    int(round(x1)),
                    int(round(y1)),
                    int(round(max(1.0, x2 - x1))),
                    int(round(max(1.0, y2 - y1))),
                ]
                payload = {
                    "bbox": bbox,
                    "confidence": round(float(box.conf.item()), 4),
                    "label": self._normalize_label(str(class_name)),
                    "source": "yolo",
                    "class_name": str(class_name),
                }
                any_boxes.append(payload)

                if any(keyword in str(class_name).lower() for keyword in self.TARGET_KEYWORDS):
                    chosen_boxes.append(payload)

            if not chosen_boxes and any_boxes:
                chosen_boxes = sorted(any_boxes, key=lambda item: item["confidence"], reverse=True)[:3]

            all_detections.append(chosen_boxes)

        return all_detections


class DetectorManager:
    def __init__(self) -> None:
        self.motion_detector = MotionDetector()
        self._yolo_detector: YOLODetector | None = None
        self._yolo_lock = Lock()

    def _get_yolo(self) -> YOLODetector:
        if self._yolo_detector is not None:
            return self._yolo_detector

        with self._yolo_lock:
            if self._yolo_detector is None:
                self._yolo_detector = YOLODetector(
                    model_path=settings.yolo_model_path,
                    conf_threshold=settings.yolo_conf_threshold,
                )

        return self._yolo_detector

    def detect(self, frame_paths: list[Path]) -> DetectorResult:
        started = time.monotonic()
        preference = settings.detector_preference.lower()
        fallback_reason: str | None = None

        if preference in {"auto", "yolo"}:
            try:
                yolo = self._get_yolo()
                detections = yolo.detect(
                    frame_paths=frame_paths,
                    time_budget_sec=settings.detector_time_budget_sec,
                )
                return DetectorResult(
                    backend="yolo",
                    frame_boxes=detections,
                    inference_seconds=round(time.monotonic() - started, 4),
                )
            except Exception as exc:
                fallback_reason = str(exc)
                logger.warning("YOLO unavailable or slow, switching to motion detector: %s", exc)

        motion_detections = self.motion_detector.detect(frame_paths)
        return DetectorResult(
            backend="motion",
            frame_boxes=motion_detections,
            inference_seconds=round(time.monotonic() - started, 4),
            fallback_reason=fallback_reason,
        )


DETECTOR_MANAGER = DetectorManager()


def run_inference(frame_paths: list[Path]) -> DetectorResult:
    if not frame_paths:
        return DetectorResult(backend="none", frame_boxes=[], inference_seconds=0.0)
    return DETECTOR_MANAGER.detect(frame_paths)
