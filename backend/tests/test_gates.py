from __future__ import annotations

from core.gates import evaluate_gate


def test_gate_passes_when_all_checks_pass() -> None:
    cfg = {
        "version": 1,
        "checks": [
            {"name": "readiness_score", "source": "readiness", "key": "readiness_score", "op": ">=", "threshold": 75, "required": True},
            {"name": "precision", "source": "metrics", "key": "precision", "op": ">=", "threshold": 0.7, "required": True},
        ],
    }
    out = evaluate_gate(
        metrics={"precision": 0.8},
        readiness={"readiness_score": 80.0},
        gates_config=cfg,
    )
    assert out["status"] == "pass"


def test_gate_fails_when_any_required_check_fails() -> None:
    cfg = {
        "version": 1,
        "checks": [
            {"name": "recall", "source": "metrics", "key": "recall", "op": ">=", "threshold": 0.7, "required": True},
        ],
    }
    out = evaluate_gate(metrics={"recall": 0.2}, gates_config=cfg)
    assert out["status"] == "fail"
    assert any(c.get("pass") is False for c in out["checks"])


def test_gate_unknown_when_missing_required_value() -> None:
    cfg = {
        "version": 1,
        "checks": [
            {"name": "delay", "source": "metrics", "key": "detection_delay_seconds", "op": "<=", "threshold": 1.5, "required": True},
        ],
    }
    out = evaluate_gate(metrics={}, gates_config=cfg)
    assert out["status"] == "unknown"

