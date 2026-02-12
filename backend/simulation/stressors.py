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
    stressors = [str(item) for item in scenario_config.get("stressors", [])]
    params = scenario_config.get("params", {})
    rng = np.random.default_rng(seed)

    keep_every = int(params.get("frame_drop", {}).get("keep_every", 1))
    keep_every = max(1, keep_every)
    drop_enabled = "frame_drop" in stressors and keep_every > 1

    stressed_frames: list[StressedFrame] = []
    dropped_indices: list[int] = []

    for sequence_idx, frame in enumerate(frames):
        image = frame.image.copy()
        applied: list[str] = []
        dropped = False

        for stressor in stressors:
            stresser_params = params.get(stressor, {})
            if stressor == "low_light":
                image = _apply_low_light(image, stresser_params)
                applied.append(stressor)
            elif stressor == "motion_blur":
                image = _apply_motion_blur(image, stresser_params)
                applied.append(stressor)
            elif stressor == "fog":
                image = _apply_fog(image, stresser_params, rng)
                applied.append(stressor)
            elif stressor == "gaussian_noise":
                image = _apply_gaussian_noise(image, stresser_params, rng)
                applied.append(stressor)
            elif stressor == "occlusion_rectangles":
                image = _apply_occlusion_rectangles(image, stresser_params, rng)
                applied.append(stressor)
            elif stressor == "compression_artifacts":
                image = _apply_compression_artifacts(image, stresser_params)
                applied.append(stressor)
            elif stressor == "frame_drop" and drop_enabled:
                if sequence_idx % keep_every != 0:
                    dropped = True
                applied.append(stressor)

        if dropped:
            dropped_indices.append(frame.frame_idx)

        stressed_frames.append(
            StressedFrame(
                frame_idx=frame.frame_idx,
                image=image,
                dropped=dropped,
                applied_stressors=applied,
            )
        )

    applied_meta = {
        "seed": seed,
        "stressors_applied": stressors,
        "stress_enabled": bool(stressors),
        "frame_drop": {
            "enabled": drop_enabled,
            "keep_every": keep_every,
            "dropped_indices": dropped_indices,
        },
    }
    return stressed_frames, applied_meta
