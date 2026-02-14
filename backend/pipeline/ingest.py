import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from core.settings import settings
from pipeline.demo_assets import ensure_golden_demo_assets, DemoAssetError


def load_scenarios_payload() -> dict[str, Any]:
    scenarios_path = Path(settings.data_dir) / "scenarios.json"
    if not scenarios_path.exists():
        raise HTTPException(status_code=500, detail="Scenario config missing")

    with scenarios_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if "scenarios" not in payload or not isinstance(payload["scenarios"], list):
        raise HTTPException(status_code=500, detail="Invalid scenario config format")

    # Inject built-in golden demo scenario (generated on demand) so fresh checkouts can demo reliably.
    if not any(item.get("id") == "demo" for item in payload["scenarios"] if isinstance(item, dict)):
        payload["scenarios"] = [
            {
                "id": "demo",
                "name": "Golden Demo (Built-in)",
                "description": "Deterministic, generated-on-demand clip + ground truth for reproducible demos.",
                "clip": "demo/demo.mp4",
                "ground_truth": "demo/demo_annotations.json",
                "video_id": "golden_demo_v1",
                "difficulty": 0.35,
                "stressors": ["gaussian_noise", "compression_artifacts"],
                "params": {
                    "gaussian_noise": {"sigma": 6.0},
                    "compression_artifacts": {"quality": 28},
                },
            },
            *payload["scenarios"],
        ]

    return payload


def get_scenario_or_404(scenario_id: str) -> dict[str, Any]:
    if scenario_id == "demo":
        # Ensure demo assets exist before returning the scenario.
        try:
            ensure_golden_demo_assets()
        except DemoAssetError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload = load_scenarios_payload()
    for scenario in payload["scenarios"]:
        if scenario.get("id") == scenario_id:
            return scenario

    raise HTTPException(status_code=404, detail=f"Unknown scenario_id: {scenario_id}")
