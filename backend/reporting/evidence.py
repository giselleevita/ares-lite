from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import cv2
from sqlalchemy.orm import Session

from core.diagnostics import collect_health_diagnostics
from core.gates import evaluate_gate, load_gates_config
from core.settings import settings
from db.models import BenchmarkBatch, BenchmarkItem, Engagement, Metric, Readiness, Run
from pipeline.blindspots import get_detection_boxes, load_ground_truth_map, render_overlay_image
from benchmarking.export import export_batch_csv


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    # backend/reporting/evidence.py -> backend/reporting -> backend -> repo root
    return Path(__file__).resolve().parents[2]


def _git_commit() -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(_repo_root()), stderr=subprocess.DEVNULL)
        commit = out.decode("utf-8", errors="replace").strip()
        return commit or None
    except Exception:
        return None


def _safe_under(base: Path, path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(base.resolve())
    except Exception:
        return False


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_write_bytes(zf: ZipFile, arcname: str, data: bytes, hashes: dict[str, str]) -> None:
    h = hashlib.sha256()
    with zf.open(arcname, "w") as handle:
        handle.write(data)
        h.update(data)
    hashes[arcname] = h.hexdigest()


def _zip_write_file(zf: ZipFile, arcname: str, path: Path, hashes: dict[str, str]) -> None:
    h = hashlib.sha256()
    with zf.open(arcname, "w") as out:
        with path.open("rb") as inp:
            while True:
                chunk = inp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                h.update(chunk)
    hashes[arcname] = h.hexdigest()


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _loads_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _run_dir(run_id: str) -> Path:
    return Path(settings.runs_dir) / run_id


def build_run_evidence_pack(
    db: Session,
    *,
    run_id: str,
    max_blindspots: int = 20,
    include_frames: bool = True,
) -> Path:
    runs_base = Path(settings.runs_dir)
    run_dir = _run_dir(run_id)
    if not _safe_under(runs_base, run_dir):
        raise ValueError("Invalid run_id path")
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        raise ValueError("Run not found")

    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "evidence_pack.zip"

    hashes: dict[str, str] = {}
    warnings: list[str] = []

    metrics_row = db.query(Metric).filter(Metric.run_id == run_id).first()
    readiness_row = db.query(Readiness).filter(Readiness.run_id == run_id).first()
    engagement_row = db.query(Engagement).filter(Engagement.run_id == run_id).first()
    metrics_payload = _loads_json(metrics_row.metrics_json if metrics_row else None)
    readiness_payload = _loads_json(readiness_row.readiness_json if readiness_row else None)
    engagement_payload = _loads_json(engagement_row.engagement_json if engagement_row else None)

    meta = _load_json_file(run_dir / "run_metadata.json") or {}
    baseline_missing = bool(metrics_payload.get("baseline_missing", meta.get("reliability_metrics", {}).get("baseline_missing", False)))

    gates_config = load_gates_config()
    gate_payload = evaluate_gate(
        run=_run_to_dict(run),
        metrics=metrics_payload,
        readiness=readiness_payload,
        engagement=engagement_payload,
        baseline_missing=baseline_missing,
        gates_config=gates_config,
    )

    # Persist the gate payload additively so report/UI/evidence stay consistent.
    meta.setdefault("gate", gate_payload)
    meta.setdefault("gates_config_snapshot", gates_config)
    try:
        (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=True), encoding="utf-8")
    except Exception:
        warnings.append("Failed to persist gate payload into run_metadata.json")

    annotation_rel = (
        meta.get("config_envelope", {}).get("scenario_snapshot", {}).get("ground_truth")
        or meta.get("config_envelope", {}).get("scenario_snapshot", {}).get("ground_truth_path")
    )
    annotation_path = Path(settings.data_dir) / str(annotation_rel) if annotation_rel else None
    gt_map = load_ground_truth_map(annotation_path) if annotation_path else {}

    blindspots = meta.get("blindspots", [])
    if not isinstance(blindspots, list):
        blindspots = []

    report_path = run_dir / "index.html"

    with ZipFile(out_path, mode="w", compression=ZIP_DEFLATED) as zf:
        _zip_write_bytes(zf, "run/run.json", json.dumps(_run_to_dict(run), indent=2, ensure_ascii=True).encode("utf-8"), hashes)
        _zip_write_bytes(zf, "metrics/metrics.json", json.dumps(metrics_payload, indent=2, ensure_ascii=True).encode("utf-8"), hashes)
        _zip_write_bytes(zf, "readiness/readiness.json", json.dumps(readiness_payload, indent=2, ensure_ascii=True).encode("utf-8"), hashes)
        _zip_write_bytes(zf, "engagement/engagement.json", json.dumps(engagement_payload, indent=2, ensure_ascii=True).encode("utf-8"), hashes)
        _zip_write_bytes(zf, "run/run_metadata.json", json.dumps(meta, indent=2, ensure_ascii=True).encode("utf-8"), hashes)
        _zip_write_bytes(zf, "gate/gate.json", json.dumps(gate_payload, indent=2, ensure_ascii=True).encode("utf-8"), hashes)

        if report_path.exists():
            _zip_write_file(zf, "report/index.html", report_path, hashes)
        else:
            warnings.append("run report index.html missing")

        # Blindspot evidence (best effort).
        blindspot_items: list[dict[str, Any]] = []
        for item in blindspots[: max(0, int(max_blindspots))]:
            if not isinstance(item, dict) or "frame_idx" not in item:
                continue
            frame_idx = int(item["frame_idx"])
            reason_tags = item.get("reason_tags", [])
            if not isinstance(reason_tags, list):
                reason_tags = []

            blindspot_items.append({"frame_idx": frame_idx, "reason_tags": reason_tags})

            if not include_frames:
                continue

            # Prefer stressed frame; fall back to extracted frame.
            stressed_path = run_dir / "stressed" / f"frame_{frame_idx:06d}.jpg"
            frame_path = stressed_path if stressed_path.exists() else (run_dir / "frames" / f"frame_{frame_idx:06d}.jpg")
            if not frame_path.exists():
                warnings.append(f"blindspot frame missing: {frame_path.name}")
                continue

            try:
                _zip_write_file(zf, f"blindspots/frame_{frame_idx:06d}.jpg", frame_path, hashes)
            except Exception:
                warnings.append(f"failed to include blindspot frame: {frame_path.name}")
                continue

            try:
                frame = cv2.imread(str(frame_path))
                if frame is None:
                    raise RuntimeError("cv2.imread returned None")
                gt_boxes = gt_map.get(str(frame_idx), [])
                if not isinstance(gt_boxes, list):
                    gt_boxes = []
                pred_boxes = get_detection_boxes(db, run_id, frame_idx)
                overlay = render_overlay_image(frame, gt_boxes, pred_boxes)
                _zip_write_bytes(zf, f"blindspots/overlay_{frame_idx:06d}.png", overlay, hashes)
            except Exception as exc:
                warnings.append(f"failed to render overlay for frame {frame_idx}: {exc}")

        _zip_write_bytes(zf, "blindspots/blindspots.json", json.dumps({"blindspots": blindspot_items}, indent=2, ensure_ascii=True).encode("utf-8"), hashes)

        manifest = _build_manifest(hashes=hashes, warnings=warnings, extra={"run_id": run_id})
        _zip_write_bytes(zf, "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=True).encode("utf-8"), hashes)

    return out_path


def build_batch_evidence_pack(db: Session, *, batch_id: str) -> Path:
    runs_base = Path(settings.runs_dir)
    batch_dir = runs_base / "_batches" / batch_id
    if not _safe_under(runs_base, batch_dir):
        raise ValueError("Invalid batch_id path")

    batch = db.query(BenchmarkBatch).filter(BenchmarkBatch.id == batch_id).first()
    if batch is None:
        raise ValueError("Benchmark batch not found")

    items = (
        db.query(BenchmarkItem)
        .filter(BenchmarkItem.batch_id == batch_id)
        .order_by(BenchmarkItem.created_at.asc(), BenchmarkItem.id.asc())
        .all()
    )

    batch_dir.mkdir(parents=True, exist_ok=True)
    out_path = batch_dir / "evidence_pack.zip"

    hashes: dict[str, str] = {}
    warnings: list[str] = []

    # Always include CSV export.
    try:
        csv_text = export_batch_csv(db, batch_id)
    except Exception as exc:
        csv_text = ""
        warnings.append(f"failed to export batch csv: {exc}")

    # Include a simple gate summary for the batch.
    gate_summary = evaluate_batch_gate(db=db, batch_id=batch_id)

    with ZipFile(out_path, mode="w", compression=ZIP_DEFLATED) as zf:
        _zip_write_bytes(zf, "batch/batch.json", json.dumps(_batch_to_dict(batch), indent=2, ensure_ascii=True).encode("utf-8"), hashes)
        _zip_write_bytes(zf, "batch/items.json", json.dumps([_item_to_dict(i) for i in items], indent=2, ensure_ascii=True).encode("utf-8"), hashes)
        _zip_write_bytes(zf, "batch/summary.json", json.dumps(_loads_json(batch.summary_json), indent=2, ensure_ascii=True).encode("utf-8"), hashes)
        _zip_write_bytes(zf, "batch/export.csv", csv_text.encode("utf-8"), hashes)
        _zip_write_bytes(zf, "gate/batch_gate.json", json.dumps(gate_summary, indent=2, ensure_ascii=True).encode("utf-8"), hashes)

        # Minimal per-run payloads (no heavy artifacts).
        run_ids = [i.run_id for i in items if i.run_id]
        if run_ids:
            runs = db.query(Run).filter(Run.id.in_(run_ids)).all()
            for run in runs:
                meta = _load_json_file(_run_dir(run.id) / "run_metadata.json") or {}
                # Keep this small.
                payload = {
                    "run": _run_to_dict(run),
                    "scenario_id": run.scenario_id,
                    "gate": meta.get("gate"),
                    "baseline_key": meta.get("baseline_key"),
                    "baseline_matched_run_id": meta.get("baseline_matched_run_id"),
                }
                _zip_write_bytes(
                    zf,
                    f"runs/{run.id}.json",
                    json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8"),
                    hashes,
                )

        manifest = _build_manifest(hashes=hashes, warnings=warnings, extra={"batch_id": batch_id})
        _zip_write_bytes(zf, "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=True).encode("utf-8"), hashes)

    return out_path


def evaluate_batch_gate(db: Session, *, batch_id: str) -> dict[str, Any]:
    batch = db.query(BenchmarkBatch).filter(BenchmarkBatch.id == batch_id).first()
    if batch is None:
        raise ValueError("Benchmark batch not found")

    items = db.query(BenchmarkItem).filter(BenchmarkItem.batch_id == batch_id).all()
    run_ids = [i.run_id for i in items if i.run_id]
    runs_by_id = {r.id: r for r in db.query(Run).filter(Run.id.in_(run_ids)).all()} if run_ids else {}

    metrics_rows = {m.run_id: _loads_json(m.metrics_json) for m in db.query(Metric).filter(Metric.run_id.in_(run_ids)).all()} if run_ids else {}
    readiness_rows = {r.run_id: _loads_json(r.readiness_json) for r in db.query(Readiness).filter(Readiness.run_id.in_(run_ids)).all()} if run_ids else {}
    engagement_rows = {e.run_id: _loads_json(e.engagement_json) for e in db.query(Engagement).filter(Engagement.run_id.in_(run_ids)).all()} if run_ids else {}

    gates_config = load_gates_config()
    results: list[dict[str, Any]] = []
    for item in items:
        if not item.run_id:
            continue
        run = runs_by_id.get(item.run_id)
        if run is None:
            continue
        # Only evaluate terminal runs.
        if run.status not in {"completed", "failed", "cancelled"}:
            continue
        metrics = metrics_rows.get(run.id, {})
        baseline_missing = bool(metrics.get("baseline_missing", False))
        gate = evaluate_gate(
            run=_run_to_dict(run),
            metrics=metrics,
            readiness=readiness_rows.get(run.id, {}),
            engagement=engagement_rows.get(run.id, {}),
            baseline_missing=baseline_missing,
            gates_config=gates_config,
        )
        results.append(
            {
                "run_id": run.id,
                "scenario_id": item.scenario_id,
                "role": item.role,
                "status": run.status,
                "gate_status": gate.get("status"),
            }
        )

    total = len(results)
    passed = sum(1 for r in results if r.get("gate_status") == "pass")
    failed = sum(1 for r in results if r.get("gate_status") == "fail")
    unknown = sum(1 for r in results if r.get("gate_status") == "unknown")

    return {
        "batch_id": batch_id,
        "batch_status": batch.status,
        "pass_rate": round(passed / total, 4) if total else None,
        "counts": {"total": total, "pass": passed, "fail": failed, "unknown": unknown},
        "items": results,
        "config": gates_config,
    }


def _build_manifest(*, hashes: dict[str, str], warnings: list[str], extra: dict[str, Any]) -> dict[str, Any]:
    diagnostics = {}
    try:
        diagnostics = collect_health_diagnostics()
    except Exception:
        diagnostics = {}

    files = [{"path": k, "sha256": v} for k, v in sorted(hashes.items(), key=lambda kv: kv[0])]
    commit = _git_commit()
    return {
        "created_at": _utcnow_iso(),
        "repo_commit": commit,
        "ffmpeg_version": diagnostics.get("ffmpeg_version"),
        "sqlite_wal_enabled": diagnostics.get("sqlite_wal_enabled"),
        "warnings": warnings,
        "files": files,
        **extra,
    }


def _run_to_dict(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "scenario_id": run.scenario_id,
        "status": run.status,
        "stage": run.stage,
        "progress": run.progress,
        "message": run.message,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "queued_at": run.queued_at.isoformat() if run.queued_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "locked_by": run.locked_by,
        "locked_at": run.locked_at.isoformat() if run.locked_at else None,
        "attempts": run.attempts,
        "cancel_requested": bool(run.cancel_requested),
        "cancelled_at": run.cancelled_at.isoformat() if run.cancelled_at else None,
    }


def _batch_to_dict(batch: BenchmarkBatch) -> dict[str, Any]:
    return {
        "id": batch.id,
        "name": batch.name,
        "status": batch.status,
        "message": batch.message,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
        "config": _loads_json(batch.config_json),
        "summary": _loads_json(batch.summary_json),
    }


def _item_to_dict(item: BenchmarkItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "scenario_id": item.scenario_id,
        "seed": item.seed,
        "status": item.status,
        "role": item.role,
        "run_id": item.run_id,
        "stress_profile": _loads_json(item.stress_profile_json),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }

