from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.settings import settings


@dataclass(frozen=True)
class GateCheckSpec:
    name: str
    source: str  # metrics|readiness|engagement|run
    key: str
    op: str
    threshold: float
    required: bool = True
    ignore_if_baseline_missing: bool = False


def _default_gate_specs() -> list[GateCheckSpec]:
    # Keep conservative defaults; users can override via backend/data/gates.json.
    return [
        GateCheckSpec(name="readiness_score", source="readiness", key="readiness_score", op=">=", threshold=75.0, required=True),
        GateCheckSpec(name="precision", source="metrics", key="precision", op=">=", threshold=0.70, required=True),
        GateCheckSpec(name="recall", source="metrics", key="recall", op=">=", threshold=0.70, required=True),
        GateCheckSpec(name="false_positive_rate_per_minute", source="metrics", key="false_positive_rate_per_minute", op="<=", threshold=0.50, required=True),
        GateCheckSpec(name="detection_delay_seconds", source="metrics", key="detection_delay_seconds", op="<=", threshold=1.50, required=True),
        GateCheckSpec(name="track_stability_index", source="metrics", key="track_stability_index", op=">=", threshold=0.60, required=True),
    ]


def _gates_path() -> Path:
    return Path(settings.data_dir) / "gates.json"


def load_gates_config() -> dict[str, Any]:
    """
    Load gates config from backend/data/gates.json.
    If missing/invalid, return built-in defaults.
    """
    path = _gates_path()
    if not path.exists():
        return {"version": 1, "checks": [spec.__dict__ for spec in _default_gate_specs()]}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "checks": [spec.__dict__ for spec in _default_gate_specs()]}
    if not isinstance(payload, dict):
        return {"version": 1, "checks": [spec.__dict__ for spec in _default_gate_specs()]}
    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks:
        return {"version": 1, "checks": [spec.__dict__ for spec in _default_gate_specs()]}
    return payload


def save_gates_config(payload: dict[str, Any]) -> None:
    """
    Save gates config atomically to backend/data/gates.json.
    Performs minimal shape validation so the service can't be bricked.
    """
    if not isinstance(payload, dict):
        raise ValueError("gates config must be an object")
    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("gates config must contain non-empty checks[]")
    for idx, item in enumerate(checks):
        if not isinstance(item, dict):
            raise ValueError(f"checks[{idx}] must be an object")
        for k in ("name", "source", "key", "op", "threshold"):
            if k not in item:
                raise ValueError(f"checks[{idx}] missing field: {k}")
        if str(item["source"]) not in {"metrics", "readiness", "engagement", "run"}:
            raise ValueError(f"checks[{idx}].source must be one of metrics|readiness|engagement|run")
        if str(item["op"]) not in {">=", "<=", ">", "<"}:
            raise ValueError(f"checks[{idx}].op must be one of >=, <=, >, <")
        try:
            float(item["threshold"])
        except Exception as exc:
            raise ValueError(f"checks[{idx}].threshold must be numeric") from exc

    path = _gates_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=True, indent=2)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(tmp_path, path)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != value:  # NaN
            return None
        return float(value)
    return None


def _compare(op: str, value: float, threshold: float) -> bool:
    if op == ">=":
        return value >= threshold
    if op == "<=":
        return value <= threshold
    if op == ">":
        return value > threshold
    if op == "<":
        return value < threshold
    raise ValueError(f"Unsupported operator: {op}")


def evaluate_gate(
    *,
    run: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    readiness: dict[str, Any] | None = None,
    engagement: dict[str, Any] | None = None,
    baseline_missing: bool = False,
    gates_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Evaluate gates and return a stable, JSON-serializable result.
    """
    run = run or {}
    metrics = metrics or {}
    readiness = readiness or {}
    engagement = engagement or {}
    gates_config = gates_config or load_gates_config()

    checks = gates_config.get("checks", [])
    if not isinstance(checks, list):
        checks = []

    results: list[dict[str, Any]] = []
    warnings: list[str] = []

    missing_required = False
    any_failed = False

    sources: dict[str, dict[str, Any]] = {
        "run": run,
        "metrics": metrics,
        "readiness": readiness,
        "engagement": engagement,
    }

    for idx, spec in enumerate(checks):
        if not isinstance(spec, dict):
            warnings.append(f"Invalid gates.checks[{idx}] (not an object)")
            continue

        name = str(spec.get("name", ""))
        source = str(spec.get("source", ""))
        key = str(spec.get("key", ""))
        op = str(spec.get("op", ""))
        required = bool(spec.get("required", True))
        ignore_if_baseline_missing = bool(spec.get("ignore_if_baseline_missing", False))

        try:
            threshold = float(spec.get("threshold"))
        except Exception:
            warnings.append(f"Invalid threshold for check '{name or idx}'")
            threshold = float("nan")

        skipped = False
        if baseline_missing and ignore_if_baseline_missing:
            skipped = True

        value_raw = sources.get(source, {}).get(key)
        value = _coerce_number(value_raw)
        passed: bool | None
        if skipped:
            passed = None
        elif value is None or not (threshold == threshold):
            passed = None
            if required:
                missing_required = True
        else:
            try:
                passed = _compare(op, value, threshold)
            except Exception as exc:
                warnings.append(f"Invalid operator for check '{name or idx}': {exc}")
                passed = None
                if required:
                    missing_required = True

        if passed is False:
            any_failed = True

        results.append(
            {
                "name": name or f"check_{idx}",
                "source": source,
                "key": key,
                "op": op,
                "threshold": threshold if threshold == threshold else None,
                "required": required,
                "ignore_if_baseline_missing": ignore_if_baseline_missing,
                "skipped": skipped,
                "value": value_raw,
                "pass": passed,
            }
        )

    status: str
    if any_failed:
        status = "fail"
    elif missing_required:
        status = "unknown"
    else:
        status = "pass"

    return {
        "status": status,
        "baseline_missing": bool(baseline_missing),
        "checks": results,
        "warnings": warnings,
        "config": gates_config,
    }

