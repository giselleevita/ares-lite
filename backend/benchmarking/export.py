from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy.orm import Session

from db.models import BenchmarkBatch, BenchmarkItem, Engagement, Metric, Readiness, Run


def _loads_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def export_batch_csv(db: Session, batch_id: str) -> str:
    """
    Export a benchmark batch as CSV.

    This is intentionally "best effort": if per-run metrics/readiness rows are missing,
    the export still succeeds with blanks instead of failing.
    """
    batch = db.query(BenchmarkBatch).filter(BenchmarkBatch.id == batch_id).first()
    if batch is None:
        raise ValueError("Benchmark batch not found")

    items = (
        db.query(BenchmarkItem)
        .filter(BenchmarkItem.batch_id == batch_id)
        .order_by(BenchmarkItem.created_at.asc(), BenchmarkItem.id.asc())
        .all()
    )

    run_ids = [item.run_id for item in items if item.run_id]
    runs_by_id: dict[str, Run] = {}
    if run_ids:
        runs_by_id = {r.id: r for r in db.query(Run).filter(Run.id.in_(run_ids)).all()}

    metrics_by_id: dict[str, dict[str, Any]] = {}
    readiness_by_id: dict[str, dict[str, Any]] = {}
    engagement_by_id: dict[str, dict[str, Any]] = {}
    if run_ids:
        metrics_by_id = {m.run_id: _loads_json(m.metrics_json) for m in db.query(Metric).filter(Metric.run_id.in_(run_ids)).all()}
        readiness_by_id = {r.run_id: _loads_json(r.readiness_json) for r in db.query(Readiness).filter(Readiness.run_id.in_(run_ids)).all()}
        engagement_by_id = {e.run_id: _loads_json(e.engagement_json) for e in db.query(Engagement).filter(Engagement.run_id.in_(run_ids)).all()}

    out = io.StringIO()
    writer = csv.DictWriter(
        out,
        fieldnames=[
            "batch_id",
            "batch_name",
            "batch_status",
            "item_id",
            "scenario_id",
            "seed",
            "stress_profile_id",
            "stress_profile_name",
            "role",
            "item_status",
            "run_id",
            "run_status",
            "run_stage",
            "run_progress",
            "baseline_missing",
            "readiness_score",
            "readiness_recommendation",
            "precision",
            "recall",
            "track_stability_index",
            "false_positive_rate_per_minute",
            "detection_delay_seconds",
            "engagement_success_rate",
            "run_error_message",
            "run_created_at",
            "run_updated_at",
        ],
        extrasaction="ignore",
    )
    writer.writeheader()

    for item in items:
        profile = _loads_json(item.stress_profile_json)
        profile_id = str(profile.get("id") or "")
        profile_name = str(profile.get("name") or profile_id or "")

        run_id = item.run_id or ""
        run = runs_by_id.get(run_id) if run_id else None
        metrics = metrics_by_id.get(run_id, {}) if run_id else {}
        readiness = readiness_by_id.get(run_id, {}) if run_id else {}
        engagement = engagement_by_id.get(run_id, {}) if run_id else {}

        writer.writerow(
            {
                "batch_id": batch.id,
                "batch_name": batch.name,
                "batch_status": batch.status,
                "item_id": item.id,
                "scenario_id": item.scenario_id,
                "seed": "" if item.seed is None else int(item.seed),
                "stress_profile_id": profile_id,
                "stress_profile_name": profile_name,
                "role": item.role,
                "item_status": item.status,
                "run_id": run_id,
                "run_status": getattr(run, "status", ""),
                "run_stage": getattr(run, "stage", ""),
                "run_progress": getattr(run, "progress", ""),
                "baseline_missing": metrics.get("baseline_missing", ""),
                "readiness_score": readiness.get("readiness_score", ""),
                "readiness_recommendation": readiness.get("recommendation", ""),
                "precision": metrics.get("precision", ""),
                "recall": metrics.get("recall", ""),
                "track_stability_index": metrics.get("track_stability_index", ""),
                "false_positive_rate_per_minute": metrics.get("false_positive_rate_per_minute", ""),
                "detection_delay_seconds": metrics.get("detection_delay_seconds", ""),
                "engagement_success_rate": engagement.get("engagement_success_rate", ""),
                "run_error_message": getattr(run, "error_message", ""),
                "run_created_at": getattr(run, "created_at", "").isoformat() if getattr(run, "created_at", None) else "",
                "run_updated_at": getattr(run, "updated_at", "").isoformat() if getattr(run, "updated_at", None) else "",
            }
        )

    return out.getvalue()

