import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from core.settings import settings


def load_scenarios_payload() -> dict[str, Any]:
    scenarios_path = Path(settings.data_dir) / "scenarios.json"
    if not scenarios_path.exists():
        raise HTTPException(status_code=500, detail="Scenario config missing")

    with scenarios_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if "scenarios" not in payload or not isinstance(payload["scenarios"], list):
        raise HTTPException(status_code=500, detail="Invalid scenario config format")

    return payload


def get_scenario_or_404(scenario_id: str) -> dict[str, Any]:
    payload = load_scenarios_payload()
    for scenario in payload["scenarios"]:
        if scenario.get("id") == scenario_id:
            return scenario

    raise HTTPException(status_code=404, detail=f"Unknown scenario_id: {scenario_id}")
