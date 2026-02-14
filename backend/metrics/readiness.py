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

    baseline_missing = bool(metrics_payload.get("baseline_missing", False))
    robustness_score: float | None = 100.0
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
            robustness_score = _clamp_0_100(float(robustness_score))
        else:
            # No baseline => we cannot score robustness evidence. Do not invent a value.
            robustness_score = None

    components: dict[str, float | None] = {
        "reliability": reliability_score,
        "stability": stability_score,
        "latency": latency_score,
        "alert_fatigue": alert_fatigue_score,
        "engagement": engagement_score,
        "robustness": robustness_score,
    }

    included_weights: dict[str, float] = {}
    weighted_scores: dict[str, float] = {}
    for key, score in components.items():
        if score is None:
            continue
        included_weights[key] = READINESS_WEIGHTS[key]
        weighted_scores[key] = float(score) * float(READINESS_WEIGHTS[key])

    denom = sum(included_weights.values()) or 1.0
    readiness_score = _clamp_0_100(sum(weighted_scores.values()) / denom)
    weighting_mode = "full"
    if robustness_score is None:
        weighting_mode = "renormalized_without_robustness"

    if readiness_score >= 75.0:
        recommendation = "READY"
    elif readiness_score >= 50.0:
        recommendation = "LIMITED"
    else:
        recommendation = "NOT_READY"

    # Explainability (additive): expose the exact effective weights and per-component contributions
    # used to compute readiness_score. This MUST NOT change readiness_score semantics.
    raw_values: dict[str, Any] = {
        "reliability": {"precision": precision, "recall": recall},
        "stability": stability,
        "latency": {"detection_delay_seconds": delay_seconds},
        "alert_fatigue": {"false_positive_rate_per_minute": fp_rate},
        "engagement": {"engagement_success_rate": success_rate, "waste_rate": waste_rate},
        "robustness": {"degradation_delta": degradation_delta},
    }

    effective_weights: dict[str, float] = {key: float(weight) / float(denom) for key, weight in included_weights.items()}
    components_list: list[dict[str, Any]] = []
    for name, score in components.items():
        if score is None:
            continue
        eff_w = float(effective_weights.get(name, 0.0))
        normalized_value = float(score)
        components_list.append(
            {
                "name": name,
                "raw_value": raw_values.get(name),
                "normalized_value": normalized_value,
                "weight": eff_w,
                "contribution": normalized_value * eff_w,
            }
        )

    pos = sorted(
        ({"name": c["name"], "contribution": float(c["contribution"])} for c in components_list if c["contribution"] > 0),
        key=lambda item: item["contribution"],
        reverse=True,
    )[:3]
    neg = sorted(
        ({"name": c["name"], "contribution": float(c["contribution"])} for c in components_list if c["contribution"] < 0),
        key=lambda item: item["contribution"],
    )[:3]

    return {
        "readiness_score": round(readiness_score, 2),
        "recommendation": recommendation,
        "weights": READINESS_WEIGHTS,
        "weighting_mode": weighting_mode,
        "baseline_missing": baseline_missing,
        "readiness_breakdown": {
            "weighting_mode": weighting_mode,
            "components": components_list,
            "top_positive_contributors": pos,
            "top_negative_contributors": neg,
        },
        "breakdown": {
            "component_scores": {
                "reliability": round(reliability_score, 2),
                "stability": round(stability_score, 2),
                "latency": round(latency_score, 2),
                "alert_fatigue": round(alert_fatigue_score, 2),
                "engagement": round(engagement_score, 2),
                "robustness": None if robustness_score is None else round(float(robustness_score), 2),
            },
            "weighted_contribution": {
                **{key: round(value, 2) for key, value in weighted_scores.items()},
                **({"robustness": None} if robustness_score is None else {}),
            },
        },
    }


def upsert_readiness(db: Any, run_id: str, readiness_payload: dict[str, Any]) -> None:
    existing = db.query(Readiness).filter(Readiness.run_id == run_id).first()
    if existing is None:
        existing = Readiness(run_id=run_id, readiness_json=json.dumps(readiness_payload))
    else:
        existing.readiness_json = json.dumps(readiness_payload)
    db.add(existing)
