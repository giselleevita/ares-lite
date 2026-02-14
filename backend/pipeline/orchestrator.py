from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.ids import new_run_id
from core.cancel import CancelledRun
from db.runs import mark_cancelled, safe_json, touch_run
from db.session import SessionLocal
from db.models import Run
from pipeline.ingest import get_scenario_or_404
from pipeline.run import process_run


def enqueue_run_request(
    db: Session,
    scenario_id: str,
    options: dict[str, Any],
) -> str:
    # Validate early so callers get a 404 instead of a queued run that will fail later.
    get_scenario_or_404(scenario_id)

    run_id = new_run_id()
    now = datetime.now(timezone.utc)
    run_record = Run(
        id=run_id,
        scenario_id=scenario_id,
        config_json=safe_json({"options": options}),
        status="queued",
        stage="queued",
        progress=0,
        message="Queued",
        error_message="",
        queued_at=now,
        updated_at=now,
    )
    db.add(run_record)
    db.commit()
    return run_id


def execute_run_job(run_id: str) -> None:
    """Background worker entrypoint. Must never raise without updating run state."""
    with SessionLocal() as db:
        run_record = db.query(Run).filter(Run.id == run_id).first()
        if run_record is None:
            return

        try:
            if bool(getattr(run_record, "cancel_requested", False)):
                mark_cancelled(db, run_id, message="Cancelled")
                db.commit()
                return

            # Load the original request options.
            try:
                config = json.loads(run_record.config_json or "{}")
            except Exception:
                config = {}
            options = config.get("options", {}) if isinstance(config, dict) else {}
            if not isinstance(options, dict):
                options = {}

            scenario = get_scenario_or_404(run_record.scenario_id)

            touch_run(
                db,
                run_id,
                status="processing",
                stage="extracting_frames",
                progress=1,
                message="Starting run",
                started=True,
                error_message="",
            )
            db.commit()

            result = process_run(
                db=db,
                run_id=run_id,
                scenario=scenario,
                options=options,
            )

            touch_run(
                db,
                run_id,
                status="completed",
                stage="completed",
                progress=100,
                message="Completed",
                finished=True,
                config_json=safe_json(result["config_envelope"]),
            )
            db.commit()
        except CancelledRun:
            mark_cancelled(db, run_id, message="Cancelled")
            db.commit()
        except HTTPException as exc:
            touch_run(
                db,
                run_id,
                status="failed",
                stage="failed",
                progress=100,
                message="Failed",
                error_message=str(exc.detail),
                finished=True,
            )
            db.commit()
        except Exception as exc:  # pragma: no cover
            touch_run(
                db,
                run_id,
                status="failed",
                stage="failed",
                progress=100,
                message="Failed",
                error_message=f"Run failed: {exc}",
                finished=True,
            )
            db.commit()


def execute_run_sync(
    db: Session,
    scenario_id: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Synchronous execution helper (demo/tests)."""
    scenario = get_scenario_or_404(scenario_id)
    run_id = new_run_id()
    now = datetime.now(timezone.utc)
    run_record = Run(
        id=run_id,
        scenario_id=scenario_id,
        config_json=safe_json({"options": options}),
        status="processing",
        stage="extracting_frames",
        progress=1,
        message="Starting run (sync)",
        error_message="",
        queued_at=now,
        started_at=now,
        updated_at=now,
    )
    db.add(run_record)
    db.commit()

    try:
        result = process_run(db=db, run_id=run_id, scenario=scenario, options=options)
        touch_run(
            db,
            run_id,
            status="completed",
            stage="completed",
            progress=100,
            message="Completed",
            finished=True,
            config_json=safe_json(result["config_envelope"]),
        )
        db.commit()
    except HTTPException:
        touch_run(db, run_id, status="failed", stage="failed", progress=100, message="Failed", finished=True)
        db.commit()
        raise

    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "status": "completed",
        "processed_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }
