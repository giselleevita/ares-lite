from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pipeline.blindspots import render_overlay


def _to_data_uri(image_bytes: bytes, media_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _build_blindspot_preview(
    run_id: str,
    stressed_dir: Path,
    blindspot: dict[str, Any],
    ground_truth_by_frame: dict[int, list[dict[str, Any]]],
    detections_by_frame: dict[int, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    frame_idx = int(blindspot["frame_idx"])
    frame_path = stressed_dir / f"frame_{frame_idx:06d}.jpg"
    if not frame_path.exists():
        return None

    frame_bytes = frame_path.read_bytes()
    overlay_bytes = render_overlay(
        frame_path=frame_path,
        ground_truth_boxes=ground_truth_by_frame.get(frame_idx, []),
        prediction_boxes=detections_by_frame.get(frame_idx, []),
    )
    return {
        "frame_idx": frame_idx,
        "reason_tags": blindspot.get("reason_tags", []),
        "frame_data_uri": _to_data_uri(frame_bytes, "image/jpeg"),
        "overlay_data_uri": _to_data_uri(overlay_bytes, "image/png"),
    }


def generate_run_report(
    run_id: str,
    scenario_id: str,
    config_envelope: dict[str, Any],
    detector_backend: str,
    fallback_reason: str | None,
    metrics_payload: dict[str, Any],
    engagement_payload: dict[str, Any],
    readiness_payload: dict[str, Any],
    gate_payload: dict[str, Any] | None,
    blindspots: list[dict[str, Any]],
    ground_truth_by_frame: dict[int, list[dict[str, Any]]],
    detections_by_frame: dict[int, list[dict[str, Any]]],
    run_dir: Path,
) -> dict[str, str]:
    template_dir = Path(__file__).resolve().parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
    )
    template = env.get_template("report.html.j2")

    stressed_dir = run_dir / "stressed"
    blindspot_previews: list[dict[str, Any]] = []
    for blindspot in blindspots[:6]:
        preview = _build_blindspot_preview(
            run_id=run_id,
            stressed_dir=stressed_dir,
            blindspot=blindspot,
            ground_truth_by_frame=ground_truth_by_frame,
            detections_by_frame=detections_by_frame,
        )
        if preview is not None:
            blindspot_previews.append(preview)

    scenario_snapshot = config_envelope.get("scenario_snapshot", {})
    rendered = template.render(
        generated_at=config_envelope.get("generated_at"),
        run_id=run_id,
        scenario_id=scenario_id,
        video_id=config_envelope.get("video_id"),
        seed_used=config_envelope.get("seed_used"),
        config=config_envelope,
        detector_backend=detector_backend,
        fallback_reason=fallback_reason,
        stress_enabled=config_envelope.get("stress_enabled"),
        scenario_name=scenario_snapshot.get("name"),
        scenario_description=scenario_snapshot.get("description"),
        scenario_difficulty=scenario_snapshot.get("difficulty"),
        scenario_stressors=scenario_snapshot.get("stressors", []),
        readiness=readiness_payload,
        metrics=metrics_payload,
        engagement=engagement_payload,
        gate=gate_payload,
        blindspots=blindspot_previews,
    )

    # Per spec: report lives directly under the run directory.
    run_report_path = run_dir / "index.html"
    run_report_path.write_text(rendered, encoding="utf-8")

    # Optional convenience pointer: atomically write the latest run id + report path.
    latest_pointer_path = run_dir.parent / "latest.json"
    payload = {
        "run_id": run_id,
        "timestamp": config_envelope.get("generated_at"),
    }
    _atomic_write_json(latest_pointer_path, payload)

    return {
        "run_report_path": str(run_report_path),
        "latest_pointer_path": str(latest_pointer_path),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=True, indent=2)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(tmp_path, path)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
