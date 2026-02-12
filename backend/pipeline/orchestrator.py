from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.ids import new_run_id
from db.models import Run
from pipeline.ingest import get_scenario_or_404
from pipeline.run import process_run


def execute_run(
    db: Session,
    scenario_id: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    scenario = get_scenario_or_404(scenario_id)
    run_id = new_run_id()

    run_record = Run(
        id=run_id,
        scenario_id=scenario_id,
        config_json=json.dumps({"options": options}),
        status="processing",
    )
    db.add(run_record)
    db.commit()

    try:
        result = process_run(
            db=db,
            run_id=run_id,
            scenario=scenario,
            options=options,
        )
        run_record.status = "completed"
        run_record.config_json = json.dumps(result["config_envelope"])
        db.add(run_record)
        db.commit()
    except HTTPException:
        run_record.status = "failed"
        db.add(run_record)
        db.commit()
        raise
    except Exception as exc:  # pragma: no cover
        run_record.status = "failed"
        db.add(run_record)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Run failed: {exc}") from exc

    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "status": run_record.status,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }
