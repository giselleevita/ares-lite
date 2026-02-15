import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.logging import configure_logging
from core.settings import settings
from core.diagnostics import collect_health_diagnostics
from db.models import Engagement, Metric, Readiness, Run
from db.session import get_db, init_db
from pipeline.job_queue import start_worker, worker_status
from pipeline.blindspots import (
    get_detection_boxes,
    get_reason_tags,
    load_ground_truth_map,
    render_overlay,
    render_overlay_image,
)
from pipeline.ingest import load_scenarios_payload
from pipeline.orchestrator import enqueue_run_request, execute_run_sync
from benchmarking.profiles import list_stress_profiles
from benchmarking.batch import (
    create_benchmark_batch,
    list_batches,
    reconcile_batch,
    batch_snapshot,
)
from benchmarking.export import export_batch_csv

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
    persist_stressed_frames: bool = False
    stress_profile_id: str | None = None


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


def _load_run_metadata(run_id: str) -> dict[str, Any] | None:
    meta_path = _run_dir(run_id) / "run_metadata.json"
    if not meta_path.exists():
        return None
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _reconstruct_stressed_frame_image(
    run_id: str,
    frame_idx: int,
    *,
    config_payload: dict[str, Any],
) -> Any:
    """Reconstruct a stressed frame in-memory from extracted frames + config.

    This is used when stressed frames are not persisted to disk.
    """
    meta = _load_run_metadata(run_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Run metadata not found for reconstruction")

    frame_indices = meta.get("frame_indices", [])
    if not isinstance(frame_indices, list):
        raise HTTPException(status_code=404, detail="Run metadata missing frame_indices")

    try:
        sequence_idx = frame_indices.index(int(frame_idx))
    except Exception:
        raise HTTPException(status_code=404, detail="Frame not part of this run") from None

    frames_dir = _run_dir(run_id) / "frames"
    extracted_path = frames_dir / f"frame_{sequence_idx + 1:06d}.jpg"
    if not extracted_path.exists():
        raise HTTPException(status_code=404, detail="Extracted frame not found for reconstruction")

    stress_enabled = bool(config_payload.get("stress_enabled", False))
    if not stress_enabled:
        image = cv2.imread(str(extracted_path))
        if image is None:
            raise HTTPException(status_code=500, detail="Failed to load extracted frame during reconstruction")
        return image

    scenario_snapshot = config_payload.get("scenario_snapshot", {})
    stressors = scenario_snapshot.get("stressors", [])
    params = scenario_snapshot.get("params", {})
    seed_used = int(config_payload.get("seed_used", 1337))

    # Local import avoids backend/main.py importing numpy during module import for all requests.
    from simulation.stressors import StressApplier  # noqa: WPS433

    applier = StressApplier(scenario_config={"stressors": stressors, "params": params}, seed=seed_used)
    stressed_image: Any | None = None

    for idx in range(sequence_idx + 1):
        path = frames_dir / f"frame_{idx + 1:06d}.jpg"
        image = cv2.imread(str(path))
        if image is None:
            raise HTTPException(status_code=500, detail="Failed to load extracted frame during reconstruction")
        stressed = applier.apply(
            frame_idx=int(frame_indices[idx]),
            image=image,
            sequence_idx=idx,
        )
        stressed_image = stressed.image

    if stressed_image is None:
        raise HTTPException(status_code=500, detail="Reconstruction failed")
    return stressed_image


@app.on_event("startup")
def on_startup() -> None:
    Path(settings.runs_dir).mkdir(parents=True, exist_ok=True)
    init_db()
    start_worker()


@app.get("/health")
def health() -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "ok", "service": "ares-lite-backend"}
    try:
        ws = worker_status()
        payload["worker_thread_alive"] = bool(ws.get("thread_alive"))
        queue_stats = ws.get("queue_stats") if isinstance(ws, dict) else None
        if isinstance(queue_stats, dict):
            payload["worker_queue_length"] = int(queue_stats.get("queued") or 0)
        payload["worker_lock_acquired"] = bool(ws.get("lock_acquired"))
    except Exception:
        pass

    # Optional ops-grade diagnostics (non-breaking fields).
    try:
        payload.update(collect_health_diagnostics())
    except Exception:
        pass
    return payload


@app.get("/api/worker")
def get_worker() -> dict[str, Any]:
    """Worker diagnostics for local dev/offline use."""
    return worker_status()


@app.get("/api/scenarios")
def get_scenarios() -> dict[str, Any]:
    return load_scenarios_payload()


@app.get("/api/stress-profiles")
def get_stress_profiles() -> dict[str, Any]:
    return {"profiles": list_stress_profiles()}


class BenchmarkRequest(BaseModel):
    name: str = "Benchmark Batch"
    scenarios: list[str] = Field(default_factory=list, min_length=1)
    # Accept preset ids or full objects. For now, UI sends preset ids.
    stress_profiles: list[Any] = Field(default_factory=lambda: ["fog"], min_length=1)
    seeds: list[int] = Field(default_factory=lambda: [12345], min_length=1)
    run_options_overrides: dict[str, Any] = Field(default_factory=lambda: {"resize": 320, "every_n_frames": 1, "max_frames": 60})


@app.post("/api/benchmarks")
def create_benchmark(payload: BenchmarkRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    batch_id, item_count = create_benchmark_batch(
        db=db,
        name=payload.name,
        scenarios=payload.scenarios,
        stress_profiles=payload.stress_profiles,
        seeds=payload.seeds,
        run_options_overrides=payload.run_options_overrides,
        validate_scenarios=True,
    )
    return {"batch_id": batch_id, "item_count": item_count}


@app.get("/api/benchmarks")
def list_benchmarks(limit: int = 25, db: Session = Depends(get_db)) -> dict[str, Any]:
    batches = list_batches(db=db, limit=limit)
    items: list[dict[str, Any]] = []
    for b in batches:
        items.append(
            {
                "id": b.id,
                "name": b.name,
                "status": b.status,
                "message": b.message,
                "created_at": b.created_at.isoformat(),
                "updated_at": b.updated_at.isoformat(),
            }
        )
    return {"batches": items}


@app.get("/api/benchmarks/{batch_id}")
def get_benchmark_batch(batch_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    # Reconcile on read so status/summary stays fresh with zero additional infra.
    snapshot = reconcile_batch(db, batch_id)
    if snapshot is None:
        snapshot = batch_snapshot(db, batch_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Benchmark batch not found")
    return snapshot


@app.get("/api/benchmarks/{batch_id}/export.csv")
def export_benchmark_batch_csv(batch_id: str, db: Session = Depends(get_db)) -> Response:
    try:
        csv_text = export_batch_csv(db, batch_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Benchmark batch not found")
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{batch_id}.csv"'},
    )


class CompareRequest(BaseModel):
    run_ids: list[str] = Field(default_factory=list, min_length=2)

def _load_json_for_run(db: Session, model: Any, run_id: str, field: str) -> dict[str, Any]:
    row = db.query(model).filter(model.run_id == run_id).first()
    if row is None:
        return {}
    try:
        payload = json.loads(getattr(row, field) or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}

def _blindspots_summary(db: Session, run_id: str) -> dict[str, Any]:
    # Prefer run_metadata.json for completed runs; fall back to DB blindspots endpoint semantics.
    meta = _load_run_metadata(run_id)
    if meta and isinstance(meta.get("blindspots"), list):
        spots = meta.get("blindspots", [])
        tags: list[str] = []
        for item in spots:
            if isinstance(item, dict):
                for t in item.get("reason_tags", []) if isinstance(item.get("reason_tags"), list) else []:
                    if isinstance(t, str) and t:
                        tags.append(t)
        counts: dict[str, int] = {}
        for t in tags:
            counts[t] = counts.get(t, 0) + 1
        top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {"count": len(spots), "top_reason_tags": [{"tag": k, "count": v} for k, v in top]}
    return {"count": 0, "top_reason_tags": []}

def _compare_payload(db: Session, run_ids: list[str]) -> dict[str, Any]:
    runs: list[Run] = [(_load_run_or_404(db, rid)) for rid in run_ids]
    items: list[dict[str, Any]] = []
    for run in runs:
        metrics_payload = _load_json_for_run(db, Metric, run.id, "metrics_json")
        readiness_payload = _load_json_for_run(db, Readiness, run.id, "readiness_json")
        engagement_payload = _load_json_for_run(db, Engagement, run.id, "engagement_json")
        items.append(
            {
                "id": run.id,
                "scenario_id": run.scenario_id,
                "status": run.status,
                "config": _load_run_config(run),
                "metrics": metrics_payload,
                "readiness": readiness_payload,
                "engagement": engagement_payload,
                "baseline_missing": bool(metrics_payload.get("baseline_missing", False)),
                "blindspots": _blindspots_summary(db, run.id),
            }
        )

    # Provide a small aligned view for common fields.
    common_fields = [
        ("readiness.readiness_score", "Readiness Score"),
        ("metrics.precision", "Precision"),
        ("metrics.recall", "Recall"),
        ("metrics.track_stability_index", "Track Stability"),
        ("metrics.false_positive_rate_per_minute", "FP/min"),
        ("metrics.detection_delay_seconds", "Delay (s)"),
    ]

    def _get_path(obj: dict[str, Any], path: str) -> Any:
        cur: Any = obj
        for part in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    return {
        "runs": items,
        "aligned": [
            {
                "field": path,
                "label": label,
                "values": {item["id"]: _get_path(item, path) for item in items},
            }
            for path, label in common_fields
        ],
    }


@app.post("/api/compare")
def compare_runs(payload: CompareRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _compare_payload(db, payload.run_ids)


@app.get("/api/runs/compare")
def compare_runs_get(ids: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    run_ids = [item.strip() for item in (ids or "").split(",") if item.strip()]
    if len(run_ids) < 2:
        raise HTTPException(status_code=422, detail="Provide at least two run ids via ids=run_a,run_b")
    return _compare_payload(db, run_ids)


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
                "stage": getattr(run, "stage", run.status),
                "progress": getattr(run, "progress", 0),
                "message": getattr(run, "message", ""),
                "created_at": run.created_at.isoformat(),
                "updated_at": getattr(run, "updated_at", run.created_at).isoformat(),
                "detector_backend": config_payload.get("detector_backend"),
                "stress_enabled": config_payload.get("stress_enabled"),
                "readiness_score": readiness_score,
            }
        )

    return {"runs": items}


@app.post("/api/run", response_model=RunResponse)
def run_scenario(payload: RunRequest, db: Session = Depends(get_db)) -> RunResponse:
    run_id = enqueue_run_request(
        db=db,
        scenario_id=payload.scenario_id,
        options=payload.options.model_dump(),
    )

    # Backward-compatible response shape: fields are placeholders until completion.
    return RunResponse(
        run_id=run_id,
        scenario_id=payload.scenario_id,
        status="queued",
        processed_at=datetime.now(timezone.utc).isoformat(),
        frames_processed=0,
        detections_written=0,
        detector_backend="pending",
        inference_seconds=0.0,
        fallback_reason=None,
    )


@app.post("/api/run/sync", response_model=RunResponse)
def run_scenario_sync(payload: RunRequest, db: Session = Depends(get_db)) -> RunResponse:
    """Debug/demo endpoint that executes synchronously in the request thread."""
    result = execute_run_sync(db=db, scenario_id=payload.scenario_id, options=payload.options.model_dump())
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
        "updated_at": getattr(run_record, "updated_at", run_record.created_at).isoformat(),
        "queued_at": getattr(run_record, "queued_at", None).isoformat() if getattr(run_record, "queued_at", None) else None,
        "started_at": getattr(run_record, "started_at", None).isoformat() if getattr(run_record, "started_at", None) else None,
        "finished_at": getattr(run_record, "finished_at", None).isoformat() if getattr(run_record, "finished_at", None) else None,
        "cancel_requested": bool(getattr(run_record, "cancel_requested", False)),
        "cancelled_at": getattr(run_record, "cancelled_at", None).isoformat() if getattr(run_record, "cancelled_at", None) else None,
        "stage": getattr(run_record, "stage", run_record.status),
        "progress": getattr(run_record, "progress", 0),
        "message": getattr(run_record, "message", ""),
        "error_message": getattr(run_record, "error_message", ""),
        "config": json.loads(run_record.config_json),
    }


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    run_record = _load_run_or_404(db, run_id)

    status = str(run_record.status)
    if status == "queued":
        from db.runs import mark_cancelled

        mark_cancelled(db, run_id, message="Cancelled")
        db.commit()
    elif status == "processing":
        from db.runs import request_cancel

        request_cancel(db, run_id)
        db.commit()
    elif status in {"completed", "failed", "cancelled"}:
        # Idempotent.
        pass
    else:
        # Unknown status: be conservative and mark cancel requested.
        from db.runs import request_cancel

        request_cancel(db, run_id)
        db.commit()

    # Return current state snapshot.
    run_record = _load_run_or_404(db, run_id)
    return {
        "id": run_record.id,
        "scenario_id": run_record.scenario_id,
        "status": run_record.status,
        "stage": getattr(run_record, "stage", run_record.status),
        "progress": getattr(run_record, "progress", 0),
        "message": getattr(run_record, "message", ""),
        "cancel_requested": bool(getattr(run_record, "cancel_requested", False)),
        "cancelled_at": getattr(run_record, "cancelled_at", None).isoformat() if getattr(run_record, "cancelled_at", None) else None,
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
def get_run_frame(run_id: str, frame_idx: int, db: Session = Depends(get_db)) -> Response:
    _load_run_or_404(db, run_id)
    frame_path = _stressed_frame_path(run_id, frame_idx)
    if frame_path.exists():
        return FileResponse(frame_path, media_type="image/jpeg")

    # If stressed frames were not persisted, reconstruct on demand.
    run_record = _load_run_or_404(db, run_id)
    config_payload = _load_run_config(run_record)
    image = _reconstruct_stressed_frame_image(run_id, frame_idx, config_payload=config_payload)
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode frame")
    return Response(content=encoded.tobytes(), media_type="image/jpeg")


@app.get("/api/runs/{run_id}/frames/{frame_idx}/overlay")
def get_run_frame_overlay(run_id: str, frame_idx: int, db: Session = Depends(get_db)) -> Response:
    run_record = _load_run_or_404(db, run_id)
    frame_path = _stressed_frame_path(run_id, frame_idx)

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
        if frame_path.exists():
            overlay_bytes = render_overlay(
                frame_path=frame_path,
                ground_truth_boxes=gt_boxes,
                prediction_boxes=pred_boxes,
            )
        else:
            config_payload = _load_run_config(run_record)
            image = _reconstruct_stressed_frame_image(run_id, frame_idx, config_payload=config_payload)
            overlay_bytes = render_overlay_image(
                image,
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
    report_path = _run_dir(run_id) / "index.html"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Run report not found")

    latest_pointer_path = Path(settings.runs_dir) / "latest.json"
    if format.lower() == "html":
        return HTMLResponse(content=report_path.read_text(encoding="utf-8"))

    payload = {
        "run_id": run_id,
        "report_path": str(report_path),
        "latest_pointer_path": str(latest_pointer_path),
    }
    return Response(content=json.dumps(payload), media_type="application/json")
