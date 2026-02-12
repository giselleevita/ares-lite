from __future__ import annotations

import base64
import shutil
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
        blindspots=blindspot_previews,
    )

    run_report_dir = run_dir / "report"
    run_report_dir.mkdir(parents=True, exist_ok=True)
    run_report_path = run_report_dir / "index.html"
    run_report_path.write_text(rendered, encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[2]
    latest_report_dir = repo_root / "results" / "latest" / "report"
    latest_report_dir.mkdir(parents=True, exist_ok=True)
    latest_report_path = latest_report_dir / "index.html"
    shutil.copy2(run_report_path, latest_report_path)

    return {
        "run_report_path": str(run_report_path),
        "latest_report_path": str(latest_report_path),
    }
