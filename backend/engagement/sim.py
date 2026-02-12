from __future__ import annotations

import json
from typing import Any

from db.models import Engagement


def simulate_engagement(
    frame_summaries: list[dict[str, Any]],
    detections_by_frame: dict[int, list[dict[str, Any]]],
    difficulty: float,
    threshold: float = 0.55,
    collateral_weight: float = 1.25,
) -> dict[str, Any]:
    engagement_attempts = 0
    successful_engagements = 0
    engagements_on_false_positives = 0
    frame_actions: list[dict[str, Any]] = []

    difficulty = max(0.0, min(1.0, float(difficulty)))

    for frame in frame_summaries:
        frame_idx = int(frame["frame_idx"])
        predictions = detections_by_frame.get(frame_idx, [])
        max_confidence = max((float(item.get("confidence", 0.0)) for item in predictions), default=0.0)
        has_tp = bool(frame.get("has_tp", False))

        action = "ENGAGE" if max_confidence >= threshold else "MONITOR"
        success = False

        if action == "ENGAGE":
            engagement_attempts += 1
            if not has_tp:
                engagements_on_false_positives += 1
            success = has_tp and (max_confidence * (1.0 - (difficulty * 0.45))) >= threshold
            if success:
                successful_engagements += 1

        frame_actions.append(
            {
                "frame_idx": frame_idx,
                "action": action,
                "max_confidence": round(max_confidence, 4),
                "has_tp": has_tp,
                "success": success,
            }
        )

    engagement_success_rate = (
        successful_engagements / engagement_attempts if engagement_attempts > 0 else 0.0
    )
    waste_rate = (
        engagements_on_false_positives / engagement_attempts if engagement_attempts > 0 else 0.0
    )
    collateral_risk_events = engagements_on_false_positives * collateral_weight

    return {
        "decision_threshold": threshold,
        "difficulty": round(difficulty, 4),
        "engagement_attempts": engagement_attempts,
        "successful_engagements": successful_engagements,
        "engagement_success_rate": round(engagement_success_rate, 4),
        "engagements_on_false_positives": engagements_on_false_positives,
        "waste_rate": round(waste_rate, 4),
        "collateral_risk_events": round(collateral_risk_events, 4),
        "frame_actions": frame_actions,
    }


def upsert_engagement(db: Any, run_id: str, engagement_payload: dict[str, Any]) -> None:
    existing = db.query(Engagement).filter(Engagement.run_id == run_id).first()
    if existing is None:
        existing = Engagement(run_id=run_id, engagement_json=json.dumps(engagement_payload))
    else:
        existing.engagement_json = json.dumps(engagement_payload)
    db.add(existing)
