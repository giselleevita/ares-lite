#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import os
import json
from pathlib import Path


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise SystemExit("ffmpeg/ffprobe not found on PATH. Install ffmpeg and retry.")


def _ensure_dataset(repo_root: Path) -> None:
    clips_dir = repo_root / "backend" / "data" / "clips"
    expected = [
        clips_dir / "urban_dusk_demo.mp4",
        clips_dir / "forest_occlusion_demo.mp4",
        clips_dir / "clutter_false_positive.mp4",
    ]
    if all(path.exists() for path in expected):
        return

    script = repo_root / "scripts" / "generate_synthetic_dataset.py"
    print("[self-check] dataset missing, generating via ffmpeg...")
    subprocess.check_call([sys.executable, str(script)])


def _ensure_golden_demo(repo_root: Path) -> None:
    sys.path.insert(0, str(repo_root / "backend"))
    try:
        from pipeline.demo_assets import ensure_golden_demo_assets  # type: ignore
    finally:
        sys.path.pop(0)

    ensure_golden_demo_assets(repo_root / "backend" / "data")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    _require_ffmpeg()
    _ensure_golden_demo(repo_root)

    # Import backend modules after we know we have ffmpeg.
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{repo_root / 'backend' / 'ares_lite_selfcheck.db'}")
    sys.path.insert(0, str(repo_root / "backend"))

    from db.models import Run  # noqa: E402
    from db.session import SessionLocal, init_db  # noqa: E402
    from pipeline.orchestrator import enqueue_run_request, execute_run_job  # noqa: E402

    init_db()

    with SessionLocal() as db:
        run_id = enqueue_run_request(
            db=db,
            scenario_id="demo",
            options={
                "resize": 320,
                "every_n_frames": 1,
                "max_frames": 60,
                "seed": 12345,
                "disable_stress": False,
            },
        )
        run = db.query(Run).filter(Run.id == run_id).first()
        assert run is not None
        assert run.status == "queued"

    # Execute the queued job (in-process) to validate pipeline end-to-end.
    execute_run_job(run_id)

    with SessionLocal() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        assert run is not None
        assert run.status == "completed", f"run failed: {run.error_message}"

    report_path = repo_root / "backend" / "data" / "runs" / run_id / "index.html"
    if not report_path.exists():
        raise SystemExit(f"report missing: {report_path}")

    latest_pointer = repo_root / "backend" / "data" / "runs" / "latest.json"
    if not latest_pointer.exists():
        raise SystemExit(f"latest pointer missing: {latest_pointer}")
    payload = json.loads(latest_pointer.read_text(encoding="utf-8"))
    if payload.get("run_id") != run_id:
        raise SystemExit(f"latest pointer not updated: expected run_id={run_id}, got {payload.get('run_id')}")
    if "timestamp" not in payload:
        raise SystemExit("latest pointer missing required field: timestamp")

    print("[self-check] OK")
    print(f"[self-check] run_id: {run_id}")
    print(f"[self-check] report: {report_path}")
    print(f"[self-check] latest pointer: {latest_pointer}")


if __name__ == "__main__":
    main()
