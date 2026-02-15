from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.settings import settings


def _profiles_path() -> Path:
    return Path(settings.data_dir) / "stress_profiles.json"


def _load_profiles_payload() -> dict[str, Any]:
    path = _profiles_path()
    if not path.exists():
        return {"profiles": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"profiles": []}
    return payload if isinstance(payload, dict) else {"profiles": []}


def list_stress_profiles() -> list[dict[str, Any]]:
    payload = _load_profiles_payload()
    profiles = payload.get("profiles", [])
    if not isinstance(profiles, list):
        return []
    out: list[dict[str, Any]] = []
    for item in profiles:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "")
        if not pid:
            continue
        out.append({"id": pid, "name": item.get("name", pid), "description": item.get("description", "")})
    return out


def get_stress_profile(profile_id: str) -> dict[str, Any] | None:
    profile_id = str(profile_id)
    payload = _load_profiles_payload()
    profiles = payload.get("profiles", [])
    if not isinstance(profiles, list):
        return None
    for item in profiles:
        if isinstance(item, dict) and str(item.get("id") or "") == profile_id:
            return item
    return None
