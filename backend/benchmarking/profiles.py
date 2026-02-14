from __future__ import annotations

from typing import Any


# Small, CPU-friendly stress profiles for benchmark suites.
# These override scenario stressors/params when selected.
STRESS_PROFILES: dict[str, dict[str, Any]] = {
    "scenario_default": {
        "name": "Scenario Default",
        "description": "Use the stressors configured by the selected scenario.",
        "stressors": None,
        "params": None,
    },
    "none": {
        "name": "None (Baseline)",
        "description": "Disable stress (baseline).",
        "stressors": [],
        "params": {},
    },
    "light_noise": {
        "name": "Light Noise + Compression",
        "description": "Mild gaussian noise and JPEG artifacts.",
        "stressors": ["gaussian_noise", "compression_artifacts"],
        "params": {"gaussian_noise": {"sigma": 6.0}, "compression_artifacts": {"quality": 28}},
    },
    "heavy_occlusion": {
        "name": "Heavy Occlusion",
        "description": "Multiple black rectangles occluding the frame.",
        "stressors": ["occlusion_rectangles"],
        "params": {"occlusion_rectangles": {"count": 4, "min_w": 30, "max_w": 120, "min_h": 24, "max_h": 110}},
    },
    "fog": {
        "name": "Fog",
        "description": "Contrast reduction + noise haze.",
        "stressors": ["fog"],
        "params": {"fog": {"contrast": 0.7, "noise_std": 6.0}},
    },
    "motion_blur": {
        "name": "Motion Blur",
        "description": "Directional blur kernel.",
        "stressors": ["motion_blur"],
        "params": {"motion_blur": {"kernel_size": 9, "axis": "horizontal"}},
    },
    "frame_drop_3": {
        "name": "Frame Drop (keep every 3)",
        "description": "Simulate dropped frames, keeping every 3rd frame.",
        "stressors": ["frame_drop"],
        "params": {"frame_drop": {"keep_every": 3}},
    },
}


def list_stress_profiles() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for profile_id, payload in STRESS_PROFILES.items():
        out.append(
            {
                "id": profile_id,
                "name": payload.get("name", profile_id),
                "description": payload.get("description", ""),
            }
        )
    return out


def get_stress_profile(profile_id: str) -> dict[str, Any] | None:
    return STRESS_PROFILES.get(str(profile_id))

