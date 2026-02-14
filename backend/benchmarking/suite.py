from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.ids import new_run_id
from db.models import BenchmarkItem, BenchmarkSuite, Run
from db.runs import safe_json
from pipeline.ingest import get_scenario_or_404


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_benchmark_suite(
    db: Session,
    *,
    name: str,
    scenario_ids: list[str],
    stress_profile_ids: list[str],
    seeds: list[int],
    base_options: dict[str, Any],
    include_baselines: bool = True,
    validate_scenarios: bool = True,
) -> str:
    """Create a benchmark suite and enqueue all runs.

    This uses the runs table + existing worker as the execution engine. Items are
    represented by normal run rows with additional metadata.
    """
    if validate_scenarios:
        for sid in scenario_ids:
            get_scenario_or_404(sid)

    suite_id = f"suite_{new_run_id()}"
    now = _utcnow()

    suite_record = BenchmarkSuite(
        id=suite_id,
        name=name or "Benchmark Suite",
        created_at=now,
        updated_at=now,
        status="queued",
        message="Queued",
        config_json=safe_json(
            {
                "scenario_ids": scenario_ids,
                "stress_profile_ids": stress_profile_ids,
                "seeds": seeds,
                "base_options": base_options,
                "include_baselines": include_baselines,
            }
        ),
    )
    db.add(suite_record)
    db.flush()

    def _enqueue_one(
        *,
        scenario_id: str,
        seed: int | None,
        stress_profile_id: str,
        role: str,
        options: dict[str, Any],
    ) -> str:
        run_id = new_run_id()
        run_now = _utcnow()
        run_record = Run(
            id=run_id,
            scenario_id=scenario_id,
            config_json=safe_json(
                {
                    "options": options,
                    "benchmark": {
                        "suite_id": suite_id,
                        "role": role,
                        "stress_profile_id": stress_profile_id,
                        "seed": seed,
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
                suite_id=suite_id,
                run_id=run_id,
                scenario_id=scenario_id,
                seed=seed,
                stress_profile_id=stress_profile_id,
                role=role,
                created_at=run_now,
            )
        )
        return run_id

    # Enqueue baselines first so baseline matching works without surprises.
    for scenario_id in scenario_ids:
        for seed in seeds:
            if include_baselines:
                baseline_options = {**base_options, "seed": seed, "disable_stress": True, "stress_profile_id": "none"}
                _enqueue_one(
                    scenario_id=scenario_id,
                    seed=seed,
                    stress_profile_id="none",
                    role="baseline",
                    options=baseline_options,
                )

            for profile_id in stress_profile_ids:
                if profile_id in {"none"}:
                    continue
                options = {**base_options, "seed": seed, "disable_stress": False, "stress_profile_id": profile_id}
                _enqueue_one(
                    scenario_id=scenario_id,
                    seed=seed,
                    stress_profile_id=profile_id,
                    role="stressed",
                    options=options,
                )

    db.commit()
    return suite_id


def suite_status_snapshot(db: Session, suite_id: str) -> dict[str, Any] | None:
    suite = db.query(BenchmarkSuite).filter(BenchmarkSuite.id == suite_id).first()
    if suite is None:
        return None

    items = db.query(BenchmarkItem).filter(BenchmarkItem.suite_id == suite_id).order_by(BenchmarkItem.id.asc()).all()
    run_ids = [item.run_id for item in items]
    runs: dict[str, Run] = {}
    if run_ids:
        for row in db.query(Run).filter(Run.id.in_(run_ids)).all():
            runs[row.id] = row

    counts = {"queued": 0, "processing": 0, "completed": 0, "failed": 0, "cancelled": 0}
    for item in items:
        r = runs.get(item.run_id)
        status = str(getattr(r, "status", "queued")) if r is not None else "queued"
        if status not in counts:
            continue
        counts[status] += 1

    total = len(items)
    terminal = counts["completed"] + counts["failed"] + counts["cancelled"]
    derived_status = "running"
    if total == 0:
        derived_status = "completed"
    elif terminal == total:
        derived_status = "failed" if counts["failed"] > 0 else "completed"

    progress = 0
    if total > 0:
        progress = int((terminal / total) * 100)

    # Do not overwrite suite_record status here; just return a derived snapshot.
    payload_items: list[dict[str, Any]] = []
    for item in items:
        r = runs.get(item.run_id)
        payload_items.append(
            {
                "run_id": item.run_id,
                "scenario_id": item.scenario_id,
                "seed": item.seed,
                "stress_profile_id": item.stress_profile_id,
                "role": item.role,
                "status": getattr(r, "status", "queued") if r is not None else "queued",
                "stage": getattr(r, "stage", getattr(r, "status", "queued")) if r is not None else "queued",
                "progress": getattr(r, "progress", 0) if r is not None else 0,
                "message": getattr(r, "message", "") if r is not None else "",
                "error_message": getattr(r, "error_message", "") if r is not None else "",
            }
        )

    # Parse suite config (best-effort).
    try:
        suite_config = json.loads(suite.config_json or "{}")
    except Exception:
        suite_config = {}

    return {
        "id": suite.id,
        "name": suite.name,
        "status": derived_status,
        "progress": progress,
        "counts": counts,
        "created_at": suite.created_at.isoformat(),
        "updated_at": suite.updated_at.isoformat(),
        "config": suite_config if isinstance(suite_config, dict) else {},
        "items": payload_items,
    }

