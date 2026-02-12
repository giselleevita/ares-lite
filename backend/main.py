import json
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.logging import configure_logging
from core.settings import settings
from db.models import Engagement, Metric, Readiness, Run
from db.session import get_db, init_db
from pipeline.blindspots import (
    get_detection_boxes,
    get_reason_tags,
    load_ground_truth_map,
    render_overlay,
)
from pipeline.ingest import load_scenarios_payload
from pipeline.orchestrator import execute_run

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


def _load_run_or_404(db: Session, run_id: str) -> Run:
    run_record = db.query(Run).filter(Run.id == run_id).first()
    if run_record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_record


def _load_run_config(run_record: Run) -> dict[str, Any]:
    try:
        payload = json.loads(run_record.config_json)
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _run_dir(run_id: str) -> Path:
    return Path(settings.runs_dir) / run_id


def _stressed_frame_path(run_id: str, frame_idx: int) -> Path:
    return _run_dir(run_id) / "stressed" / f"frame_{frame_idx:06d}.jpg"


def _annotation_path_from_config(config_payload: dict[str, Any]) -> Path | None:
    scenario_snapshot = config_payload.get("scenario_snapshot", {})
    annotation_rel = scenario_snapshot.get("ground_truth")
    if not annotation_rel:
        return None
    return Path(settings.data_dir) / str(annotation_rel)


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


@app.get("/api/runs")
def list_runs(limit: int = 25, db: Session = Depends(get_db)) -> dict[str, Any]:
    max_limit = max(1, min(limit, 100))
    runs = db.query(Run).order_by(Run.created_at.desc()).limit(max_limit).all()

    items: list[dict[str, Any]] = []
    for run in runs:
        config_payload = _load_run_config(run)
        readiness_row = db.query(Readiness).filter(Readiness.run_id == run.id).first()
        readiness_score = None
        if readiness_row is not None:
            try:
                readiness_score = json.loads(readiness_row.readiness_json).get("readiness_score")
            except Exception:
                readiness_score = None

        items.append(
            {
                "id": run.id,
                "scenario_id": run.scenario_id,
                "status": run.status,
                "created_at": run.created_at.isoformat(),
                "detector_backend": config_payload.get("detector_backend"),
                "stress_enabled": config_payload.get("stress_enabled"),
                "readiness_score": readiness_score,
            }
        )

    return {"runs": items}


@app.post("/api/run", response_model=RunResponse)
def run_scenario(payload: RunRequest, db: Session = Depends(get_db)) -> RunResponse:
    result = execute_run(
        db=db,
        scenario_id=payload.scenario_id,
        options=payload.options.model_dump(),
    )

    return RunResponse(
        run_id=result["run_id"],
        scenario_id=payload.scenario_id,
        status=result["status"],
        processed_at=result["processed_at"],
        frames_processed=result["frames_processed"],
        detections_written=result["detections_written"],
        detector_backend=result["detector_backend"],
        inference_seconds=result["inference_seconds"],
        fallback_reason=result.get("fallback_reason"),
    )


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    run_record = _load_run_or_404(db, run_id)

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


@app.get("/api/runs/{run_id}/blindspots")
def get_run_blindspots(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    run_record = _load_run_or_404(db, run_id)
    metric_record = db.query(Metric).filter(Metric.run_id == run_id).first()
    if metric_record is None:
        raise HTTPException(status_code=404, detail="Metrics not found for run")

    metrics_payload = json.loads(metric_record.metrics_json)
    frame_indices = metrics_payload.get("false_negative_frames", {}).get("frames", [])
    config_payload = _load_run_config(run_record)
    stressors = config_payload.get("scenario_snapshot", {}).get("stressors", [])

    annotation_path = _annotation_path_from_config(config_payload)
    ground_truth_map = load_ground_truth_map(annotation_path) if annotation_path else {}

    blindspots: list[dict[str, Any]] = []
    for frame_idx in frame_indices:
        idx = int(frame_idx)
        gt_boxes = ground_truth_map.get(str(idx), [])
        reason_tags = get_reason_tags(frame_idx=idx, gt_boxes=gt_boxes, stressors=stressors)
        blindspots.append(
            {
                "frame_idx": idx,
                "reason_tags": reason_tags,
                "frame_url": f"/api/runs/{run_id}/frames/{idx}",
                "overlay_url": f"/api/runs/{run_id}/frames/{idx}/overlay",
            }
        )

    return {"run_id": run_id, "blindspots": blindspots, "count": len(blindspots)}


@app.get("/api/runs/{run_id}/frames/{frame_idx}")
def get_run_frame(run_id: str, frame_idx: int, db: Session = Depends(get_db)) -> FileResponse:
    _load_run_or_404(db, run_id)
    frame_path = _stressed_frame_path(run_id, frame_idx)
    if not frame_path.exists():
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(frame_path, media_type="image/jpeg")


@app.get("/api/runs/{run_id}/frames/{frame_idx}/overlay")
def get_run_frame_overlay(run_id: str, frame_idx: int, db: Session = Depends(get_db)) -> Response:
    run_record = _load_run_or_404(db, run_id)
    frame_path = _stressed_frame_path(run_id, frame_idx)
    if not frame_path.exists():
        raise HTTPException(status_code=404, detail="Frame not found")

    overlay_dir = _run_dir(run_id) / "overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = overlay_dir / f"frame_{frame_idx:06d}.png"
    if overlay_path.exists():
        return FileResponse(overlay_path, media_type="image/png")

    config_payload = _load_run_config(run_record)
    annotation_path = _annotation_path_from_config(config_payload)
    ground_truth_map = load_ground_truth_map(annotation_path) if annotation_path else {}
    gt_boxes = ground_truth_map.get(str(frame_idx), [])
    pred_boxes = get_detection_boxes(db=db, run_id=run_id, frame_idx=frame_idx)

    try:
        overlay_bytes = render_overlay(
            frame_path=frame_path,
            ground_truth_boxes=gt_boxes,
            prediction_boxes=pred_boxes,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    overlay_path.write_bytes(overlay_bytes)
    return Response(content=overlay_bytes, media_type="image/png")


@app.get("/api/runs/{run_id}/report")
def get_run_report(run_id: str, format: str = "json", db: Session = Depends(get_db)) -> Response:
    _load_run_or_404(db, run_id)
    report_path = _run_dir(run_id) / "report" / "index.html"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Run report not found")

    latest_path = Path(__file__).resolve().parents[1] / "results" / "latest" / "report" / "index.html"
    if format.lower() == "html":
        return HTMLResponse(content=report_path.read_text(encoding="utf-8"))

    payload = {
        "run_id": run_id,
        "report_path": str(report_path),
        "latest_report_path": str(latest_path),
    }
    return Response(content=json.dumps(payload), media_type="application/json")
