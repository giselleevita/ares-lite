from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np


@dataclass
class FrameRecord:
    frame_idx: int
    image: np.ndarray


@dataclass
class StressedFrame:
    frame_idx: int
    image: np.ndarray
    dropped: bool = False
    applied_stressors: list[str] = field(default_factory=list)


class StressApplier:
    def __init__(self, scenario_config: dict[str, Any], seed: int) -> None:
        self.stressors = [str(item) for item in scenario_config.get("stressors", [])]
        self.params = scenario_config.get("params", {}) or {}
        self.rng = np.random.default_rng(seed)
        self.seed = int(seed)

        keep_every = int((self.params.get("frame_drop", {}) or {}).get("keep_every", 1))
        keep_every = max(1, keep_every)
        self.keep_every = keep_every
        self.drop_enabled = "frame_drop" in set(self.stressors) and keep_every > 1

        self._dropped_indices: list[int] = []

    def apply(self, *, frame_idx: int, image: np.ndarray, sequence_idx: int) -> StressedFrame:
        out = image.copy()
        applied: list[str] = []
        dropped = False

        for stressor in self.stressors:
            stresser_params = (self.params.get(stressor, {}) or {}) if isinstance(self.params, dict) else {}
            if stressor == "low_light":
                out = _apply_low_light(out, stresser_params)
                applied.append(stressor)
            elif stressor == "motion_blur":
                out = _apply_motion_blur(out, stresser_params)
                applied.append(stressor)
            elif stressor == "fog":
                out = _apply_fog(out, stresser_params, self.rng)
                applied.append(stressor)
            elif stressor == "gaussian_noise":
                out = _apply_gaussian_noise(out, stresser_params, self.rng)
                applied.append(stressor)
            elif stressor == "occlusion_rectangles":
                out = _apply_occlusion_rectangles(out, stresser_params, self.rng)
                applied.append(stressor)
            elif stressor == "compression_artifacts":
                out = _apply_compression_artifacts(out, stresser_params)
                applied.append(stressor)
            elif stressor == "frame_drop":
                if self.drop_enabled and sequence_idx % self.keep_every != 0:
                    dropped = True
                applied.append(stressor)

        if dropped:
            self._dropped_indices.append(int(frame_idx))

        return StressedFrame(frame_idx=int(frame_idx), image=out, dropped=dropped, applied_stressors=applied)

    def meta(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "stressors_applied": self.stressors,
            "stress_enabled": bool(self.stressors),
            "frame_drop": {
                "enabled": self.drop_enabled,
                "keep_every": self.keep_every,
                "dropped_indices": self._dropped_indices,
            },
        }


def _apply_low_light(image: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    gamma = float(params.get("gamma", 0.85))
    brightness_scale = float(params.get("brightness_scale", 0.8))
    gamma = max(0.05, gamma)
    brightness_scale = max(0.05, min(1.5, brightness_scale))

    normalized = image.astype(np.float32) / 255.0
    adjusted = np.power(normalized, gamma) * brightness_scale
    return np.clip(adjusted * 255.0, 0, 255).astype(np.uint8)


def _apply_motion_blur(image: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    kernel_size = int(params.get("kernel_size", 7))
    axis = str(params.get("axis", "horizontal")).lower()
    if kernel_size < 3:
        kernel_size = 3
    if kernel_size % 2 == 0:
        kernel_size += 1

    kernel = np.zeros((kernel_size, kernel_size), dtype=np.float32)
    if axis == "vertical":
        kernel[:, kernel_size // 2] = 1.0 / kernel_size
    else:
        kernel[kernel_size // 2, :] = 1.0 / kernel_size
    return cv2.filter2D(image, -1, kernel)


def _apply_fog(image: np.ndarray, params: dict[str, Any], rng: np.random.Generator) -> np.ndarray:
    contrast = float(params.get("contrast", 0.72))
    noise_std = float(params.get("noise_std", 5.0))
    contrast = max(0.2, min(1.0, contrast))
    noise_std = max(0.0, min(25.0, noise_std))

    fog_color = np.full_like(image, 200, dtype=np.uint8)
    mixed = cv2.addWeighted(image, contrast, fog_color, 1.0 - contrast, 0)
    noise = rng.normal(0.0, noise_std, size=image.shape).astype(np.float32)
    with_noise = mixed.astype(np.float32) + noise
    return np.clip(with_noise, 0, 255).astype(np.uint8)


def _apply_gaussian_noise(image: np.ndarray, params: dict[str, Any], rng: np.random.Generator) -> np.ndarray:
    sigma = float(params.get("sigma", 9.0))
    sigma = max(0.0, min(60.0, sigma))
    noise = rng.normal(0.0, sigma, size=image.shape).astype(np.float32)
    noisy = image.astype(np.float32) + noise
    return np.clip(noisy, 0, 255).astype(np.uint8)


def _apply_occlusion_rectangles(
    image: np.ndarray,
    params: dict[str, Any],
    rng: np.random.Generator,
) -> np.ndarray:
    out = image.copy()
    count = int(params.get("count", 2))
    min_w = int(params.get("min_w", 36))
    max_w = int(params.get("max_w", 120))
    min_h = int(params.get("min_h", 28))
    max_h = int(params.get("max_h", 110))

    height, width = out.shape[:2]
    for _ in range(max(0, count)):
        rect_w = int(rng.integers(max(8, min_w), max(max_w, min_w + 1)))
        rect_h = int(rng.integers(max(8, min_h), max(max_h, min_h + 1)))
        x_max = max(1, width - rect_w)
        y_max = max(1, height - rect_h)
        x = int(rng.integers(0, x_max))
        y = int(rng.integers(0, y_max))
        cv2.rectangle(out, (x, y), (x + rect_w, y + rect_h), (0, 0, 0), thickness=-1)

    return out


def _apply_compression_artifacts(image: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    quality = int(params.get("quality", 28))
    quality = max(5, min(95, quality))
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return image
    decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    return decoded if decoded is not None else image


def apply_stress_pipeline(
    frames: list[FrameRecord],
    scenario_config: dict[str, Any],
    seed: int,
) -> tuple[list[StressedFrame], dict[str, Any]]:
    applier = StressApplier(scenario_config=scenario_config, seed=seed)
    stressed_frames: list[StressedFrame] = []
    for sequence_idx, frame in enumerate(frames):
        stressed_frames.append(
            applier.apply(frame_idx=frame.frame_idx, image=frame.image, sequence_idx=sequence_idx)
        )
    return stressed_frames, applier.meta()
