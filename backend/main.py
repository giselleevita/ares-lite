import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.ids import new_run_id
from core.logging import configure_logging
from core.settings import settings
from db.models import Engagement, Metric, Readiness, Run
from db.session import get_db, init_db
from pipeline.ingest import get_scenario_or_404, load_scenarios_payload
from pipeline.run import process_run

configure_logging()

app = FastAPI(title="ARES Lite Backend", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunOptions(BaseModel):
    resize: int = Field(default=640, ge=160, le=1920)
    every_n_frames: int = Field(default=2, ge=1, le=60)
    max_frames: int = Field(default=120, ge=1, le=1200)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    disable_stress: bool = False


class RunRequest(BaseModel):
    scenario_id: str
    options: RunOptions = Field(default_factory=RunOptions)


class RunResponse(BaseModel):
    run_id: str
    scenario_id: str
    status: str
    processed_at: str
    frames_processed: int
    detections_written: int
    detector_backend: str
    inference_seconds: float
    fallback_reason: str | None = None


@app.on_event("startup")
def on_startup() -> None:
    Path(settings.runs_dir).mkdir(parents=True, exist_ok=True)
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ares-lite-backend"}


@app.get("/api/scenarios")
def get_scenarios() -> dict[str, Any]:
    return load_scenarios_payload()


@app.post("/api/run", response_model=RunResponse)
def run_scenario(payload: RunRequest, db: Session = Depends(get_db)) -> RunResponse:
    scenario = get_scenario_or_404(payload.scenario_id)
    run_id = new_run_id()

    run_record = Run(
        id=run_id,
        scenario_id=payload.scenario_id,
        config_json=json.dumps({"options": payload.options.model_dump()}),
        status="processing",
    )
    db.add(run_record)
    db.commit()

    try:
        result = process_run(
            db=db,
            run_id=run_id,
            scenario=scenario,
            options=payload.options.model_dump(),
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

    return RunResponse(
        run_id=run_id,
        scenario_id=payload.scenario_id,
        status=run_record.status,
        processed_at=datetime.now(timezone.utc).isoformat(),
        frames_processed=result["frames_processed"],
        detections_written=result["detections_written"],
        detector_backend=result["detector_backend"],
        inference_seconds=result["inference_seconds"],
        fallback_reason=result.get("fallback_reason"),
    )


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    run_record = db.query(Run).filter(Run.id == run_id).first()
    if run_record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return {
        "id": run_record.id,
        "scenario_id": run_record.scenario_id,
        "status": run_record.status,
        "created_at": run_record.created_at.isoformat(),
        "config": json.loads(run_record.config_json),
    }


@app.get("/api/runs/{run_id}/metrics")
def get_run_metrics(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    metric_record = db.query(Metric).filter(Metric.run_id == run_id).first()
    if metric_record is None:
        raise HTTPException(status_code=404, detail="Metrics not found for run")
    return {
        "run_id": run_id,
        "metrics": json.loads(metric_record.metrics_json),
    }


@app.get("/api/runs/{run_id}/engagement")
def get_run_engagement(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    engagement_record = db.query(Engagement).filter(Engagement.run_id == run_id).first()
    if engagement_record is None:
        raise HTTPException(status_code=404, detail="Engagement results not found for run")
    return {
        "run_id": run_id,
        "engagement": json.loads(engagement_record.engagement_json),
    }


@app.get("/api/runs/{run_id}/readiness")
def get_run_readiness(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    readiness_record = db.query(Readiness).filter(Readiness.run_id == run_id).first()
    if readiness_record is None:
        raise HTTPException(status_code=404, detail="Readiness results not found for run")
    return {
        "run_id": run_id,
        "readiness": json.loads(readiness_record.readiness_json),
    }
