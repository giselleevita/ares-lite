from __future__ import annotations

import json
from typing import Any

from db.models import Readiness

READINESS_WEIGHTS = {
    "reliability": 0.35,
    "stability": 0.20,
    "latency": 0.15,
    "alert_fatigue": 0.10,
    "engagement": 0.15,
    "robustness": 0.05,
}


def _clamp_0_100(value: float) -> float:
    return max(0.0, min(100.0, value))


def compute_readiness(
    metrics_payload: dict[str, Any],
    engagement_payload: dict[str, Any],
    stress_enabled: bool,
) -> dict[str, Any]:
    precision = float(metrics_payload.get("precision", 0.0))
    recall = float(metrics_payload.get("recall", 0.0))
    stability = float(metrics_payload.get("track_stability_index", 0.0))
    delay_seconds = metrics_payload.get("detection_delay_seconds")
    fp_rate = float(metrics_payload.get("false_positive_rate_per_minute", 0.0))
    success_rate = float(engagement_payload.get("engagement_success_rate", 0.0))
    waste_rate = float(engagement_payload.get("waste_rate", 0.0))

    reliability_score = _clamp_0_100(((precision + recall) / 2.0) * 100.0)
    stability_score = _clamp_0_100(stability * 100.0)
    latency_score = _clamp_0_100(100.0 - (float(delay_seconds or 10.0) * 20.0))
    alert_fatigue_score = _clamp_0_100(100.0 - (fp_rate * 22.0))
    engagement_score = _clamp_0_100(success_rate * (1.0 - waste_rate) * 100.0)

    robustness_score = 100.0
    degradation_delta = metrics_payload.get("degradation_delta")
    if stress_enabled:
        if degradation_delta:
            precision_delta = float(degradation_delta.get("precision_delta", 0.0))
            recall_delta = float(degradation_delta.get("recall_delta", 0.0))
            stability_delta = float(degradation_delta.get("stability_delta", 0.0))
            fp_delta = float(degradation_delta.get("fp_rate_per_minute_delta", 0.0))
            delay_delta = float(degradation_delta.get("detection_delay_seconds_delta", 0.0))

            robustness_score += precision_delta * 40.0
            robustness_score += recall_delta * 40.0
            robustness_score += stability_delta * 25.0
            robustness_score -= max(0.0, fp_delta) * 12.0
            robustness_score -= max(0.0, delay_delta) * 10.0
            robustness_score = _clamp_0_100(robustness_score)
        else:
            robustness_score = 70.0

    weighted_scores = {
        "reliability": reliability_score * READINESS_WEIGHTS["reliability"],
        "stability": stability_score * READINESS_WEIGHTS["stability"],
        "latency": latency_score * READINESS_WEIGHTS["latency"],
        "alert_fatigue": alert_fatigue_score * READINESS_WEIGHTS["alert_fatigue"],
        "engagement": engagement_score * READINESS_WEIGHTS["engagement"],
        "robustness": robustness_score * READINESS_WEIGHTS["robustness"],
    }
    readiness_score = _clamp_0_100(sum(weighted_scores.values()))

    if readiness_score >= 75.0:
        recommendation = "READY"
    elif readiness_score >= 50.0:
        recommendation = "LIMITED"
    else:
        recommendation = "NOT_READY"

    return {
        "readiness_score": round(readiness_score, 2),
        "recommendation": recommendation,
        "weights": READINESS_WEIGHTS,
        "breakdown": {
            "component_scores": {
                "reliability": round(reliability_score, 2),
                "stability": round(stability_score, 2),
                "latency": round(latency_score, 2),
                "alert_fatigue": round(alert_fatigue_score, 2),
                "engagement": round(engagement_score, 2),
                "robustness": round(robustness_score, 2),
            },
            "weighted_contribution": {key: round(value, 2) for key, value in weighted_scores.items()},
        },
    }


def upsert_readiness(db: Any, run_id: str, readiness_payload: dict[str, Any]) -> None:
    existing = db.query(Readiness).filter(Readiness.run_id == run_id).first()
    if existing is None:
        existing = Readiness(run_id=run_id, readiness_json=json.dumps(readiness_payload))
    else:
        existing.readiness_json = json.dumps(readiness_payload)
    db.add(existing)
