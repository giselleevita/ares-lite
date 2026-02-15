from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any

from sqlalchemy.orm import Session

from core.ids import new_run_id
from db.models import BenchmarkBatch, BenchmarkItem, Engagement, Metric, Readiness, Run
from db.runs import safe_json, touch_run
from pipeline.ingest import get_scenario_or_404
from benchmarking.profiles import get_stress_profile


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_profile_json(profile: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(profile, dict):
        return profile
    pid = str(profile)
    payload = get_stress_profile(pid)
    if payload is None:
        raise ValueError(f"Unknown stress profile: {pid}")
    return payload


def create_benchmark_batch(
    db: Session,
    *,
    name: str,
    scenarios: list[str],
    stress_profiles: list[str | dict[str, Any]],
    seeds: list[int],
    run_options_overrides: dict[str, Any],
    validate_scenarios: bool = True,
) -> tuple[str, int]:
    """Create a benchmark batch, items, and enqueue runs using the existing runs queue."""
    if validate_scenarios:
        for sid in scenarios:
            get_scenario_or_404(sid)

    batch_id = f"batch_{new_run_id()}"
    now = _utcnow()

    batch = BenchmarkBatch(
        id=batch_id,
        name=name or "Benchmark Batch",
        created_at=now,
        updated_at=now,
        status="queued",
        message="Queued",
        config_json=safe_json(
            {
                "scenarios": scenarios,
                "stress_profiles": stress_profiles,
                "seeds": seeds,
                "run_options_overrides": run_options_overrides,
            }
        ),
        summary_json="{}",
    )
    db.add(batch)
    db.flush()

    item_count = 0

    for scenario_id in scenarios:
        for seed in seeds:
            for profile in stress_profiles:
                profile_json = _ensure_profile_json(profile)
                profile_id = str(profile_json.get("id") or "custom")

                options = dict(run_options_overrides or {})
                options["seed"] = int(seed)
                options["stress_profile_id"] = profile_id

                # Baseline profile enforces disable_stress.
                role = "stressed"
                if profile_id == "baseline":
                    options["disable_stress"] = True
                    role = "baseline"
                else:
                    options.setdefault("disable_stress", False)

                run_id = new_run_id()
                run_now = _utcnow()
                run_record = Run(
                    id=run_id,
                    scenario_id=scenario_id,
                    config_json=safe_json(
                        {
                            "options": options,
                            "benchmark": {
                                "batch_id": batch_id,
                                "seed": seed,
                                "stress_profile": profile_json,
                                "role": role,
                                "created_at": run_now.isoformat(),
                            },
                        }
                    ),
                    status="queued",
                    stage="queued",
                    progress=0,
                    message="Queued",
                    error_message="",
                    queued_at=run_now,
                    updated_at=run_now,
                )
                db.add(run_record)
                db.flush()
                db.add(
                    BenchmarkItem(
                        batch_id=batch_id,
                        scenario_id=scenario_id,
                        seed=seed,
                        stress_profile_json=safe_json(profile_json),
                        run_id=run_id,
                        status="queued",
                        role=role,
                        created_at=run_now,
                    )
                )
                item_count += 1

    db.commit()
    return batch_id, item_count


def list_batches(db: Session, limit: int = 25) -> list[BenchmarkBatch]:
    return db.query(BenchmarkBatch).order_by(BenchmarkBatch.created_at.desc()).limit(max(1, min(limit, 100))).all()


def _load_json_row(row: Any, field: str) -> dict[str, Any]:
    try:
        payload = json.loads(getattr(row, field) or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _compute_summary(
    db: Session,
    items: list[BenchmarkItem],
    runs_by_id: dict[str, Run],
) -> dict[str, Any]:
    readiness_scores: list[float] = []
    readiness_by_scenario: dict[str, list[float]] = defaultdict(list)
    readiness_by_profile: dict[str, list[float]] = defaultdict(list)
    failures: list[dict[str, Any]] = []
    blindspot_reasons: Counter[str] = Counter()

    run_ids = [item.run_id for item in items if item.run_id]
    metrics_rows = {m.run_id: _load_json_row(m, "metrics_json") for m in db.query(Metric).filter(Metric.run_id.in_(run_ids)).all()} if run_ids else {}
    readiness_rows = {r.run_id: _load_json_row(r, "readiness_json") for r in db.query(Readiness).filter(Readiness.run_id.in_(run_ids)).all()} if run_ids else {}
    engagement_rows = {e.run_id: _load_json_row(e, "engagement_json") for e in db.query(Engagement).filter(Engagement.run_id.in_(run_ids)).all()} if run_ids else {}

    for item in items:
        run_id = item.run_id
        if not run_id:
            continue
        run = runs_by_id.get(run_id)
        status = str(getattr(run, "status", "queued")) if run else "queued"
        if status in {"failed", "cancelled"}:
            failures.append(
                {
                    "run_id": run_id,
                    "scenario_id": item.scenario_id,
                    "status": status,
                    "error_message": getattr(run, "error_message", "") if run else "",
                }
            )
            continue

        readiness_payload = readiness_rows.get(run_id, {})
        score = readiness_payload.get("readiness_score")
        if isinstance(score, (int, float)):
            readiness_scores.append(float(score))
            readiness_by_scenario[item.scenario_id].append(float(score))

            # Extract profile id from stored stress_profile_json.
            try:
                p = json.loads(item.stress_profile_json or "{}")
            except Exception:
                p = {}
            profile_id = str(p.get("id") or "unknown")
            readiness_by_profile[profile_id].append(float(score))

        # Blindspot reasons: pull from metrics frame summaries if available (no overlays).
        metrics_payload = metrics_rows.get(run_id, {})
        frame_summaries = metrics_payload.get("frame_summaries", [])
        if isinstance(frame_summaries, list):
            for fs in frame_summaries:
                if not isinstance(fs, dict):
                    continue
                tags = fs.get("reason_tags", [])
                if isinstance(tags, list):
                    for t in tags:
                        if isinstance(t, str) and t:
                            blindspot_reasons[t] += 1

        # Keep engagement payload present for future UI, but don't aggregate now.
        _ = engagement_rows.get(run_id, {})

    overall = {
        "count": len(readiness_scores),
        "mean_readiness": round(mean(readiness_scores), 3) if readiness_scores else None,
        "median_readiness": round(median(readiness_scores), 3) if readiness_scores else None,
        "worst_readiness": round(min(readiness_scores), 3) if readiness_scores else None,
        "best_readiness": round(max(readiness_scores), 3) if readiness_scores else None,
        "pass_rate_ready": None,
    }
    if readiness_scores:
        # READY threshold aligns with readiness recommendation logic: >= 75
        overall["pass_rate_ready"] = round(sum(1 for s in readiness_scores if s >= 75.0) / len(readiness_scores), 4)

    by_scenario = {k: {"count": len(v), "mean": round(mean(v), 3) if v else None, "worst": round(min(v), 3) if v else None} for k, v in readiness_by_scenario.items()}
    by_profile = {k: {"count": len(v), "mean": round(mean(v), 3) if v else None, "worst": round(min(v), 3) if v else None} for k, v in readiness_by_profile.items()}

    return {
        "overall": overall,
        "by_scenario": by_scenario,
        "by_stress_profile": by_profile,
        "top_blindspot_reasons": [{"reason": k, "count": int(c)} for k, c in blindspot_reasons.most_common(10)],
        "failures": failures,
    }


def reconcile_batch(db: Session, batch_id: str) -> dict[str, Any] | None:
    """Update batch/item statuses and compute summary_json when terminal."""
    batch = db.query(BenchmarkBatch).filter(BenchmarkBatch.id == batch_id).first()
    if batch is None:
        return None

    items = db.query(BenchmarkItem).filter(BenchmarkItem.batch_id == batch_id).order_by(BenchmarkItem.id.asc()).all()
    run_ids = [item.run_id for item in items if item.run_id]
    runs_by_id: dict[str, Run] = {}
    if run_ids:
        for r in db.query(Run).filter(Run.id.in_(run_ids)).all():
            runs_by_id[r.id] = r

    # Update item statuses from run statuses.
    for item in items:
        if not item.run_id:
            item.status = "queued"
            continue
        run = runs_by_id.get(item.run_id)
        if run is None:
            item.status = "queued"
            continue
        item.status = str(getattr(run, "status", "queued"))
        db.add(item)

    counts = Counter([str(it.status) for it in items])
    total = len(items)
    terminal = counts.get("completed", 0) + counts.get("failed", 0) + counts.get("cancelled", 0)
    any_started = counts.get("processing", 0) > 0 or terminal > 0
    status = "queued"
    if any_started and terminal < total:
        status = "processing"
    if total > 0 and terminal == total:
        status = "failed" if counts.get("failed", 0) > 0 else "completed"

    batch.status = status
    batch.updated_at = _utcnow()
    batch.message = f"{terminal}/{total} complete"

    if status in {"completed", "failed"}:
        # Compute summary once; recompute if empty.
        try:
            existing = json.loads(batch.summary_json or "{}")
        except Exception:
            existing = {}
        if not isinstance(existing, dict) or not existing:
            summary = _compute_summary(db, items, runs_by_id)
            batch.summary_json = safe_json(summary)

    db.add(batch)
    db.commit()

    return batch_snapshot(db, batch_id)


def batch_snapshot(db: Session, batch_id: str) -> dict[str, Any] | None:
    batch = db.query(BenchmarkBatch).filter(BenchmarkBatch.id == batch_id).first()
    if batch is None:
        return None
    items = db.query(BenchmarkItem).filter(BenchmarkItem.batch_id == batch_id).order_by(BenchmarkItem.id.asc()).all()

    try:
        config_payload = json.loads(batch.config_json or "{}")
    except Exception:
        config_payload = {}
    try:
        summary_payload = json.loads(batch.summary_json or "{}")
    except Exception:
        summary_payload = {}

    out_items: list[dict[str, Any]] = []
    for item in items:
        try:
            profile = json.loads(item.stress_profile_json or "{}")
        except Exception:
            profile = {}
        out_items.append(
            {
                "id": item.id,
                "batch_id": item.batch_id,
                "scenario_id": item.scenario_id,
                "seed": item.seed,
                "stress_profile": profile,
                "run_id": item.run_id,
                "status": item.status,
                "role": item.role,
            }
        )

    return {
        "id": batch.id,
        "name": batch.name,
        "status": batch.status,
        "message": batch.message,
        "created_at": batch.created_at.isoformat(),
        "updated_at": batch.updated_at.isoformat(),
        "config": config_payload if isinstance(config_payload, dict) else {},
        "summary": summary_payload if isinstance(summary_payload, dict) else {},
        "items": out_items,
    }

