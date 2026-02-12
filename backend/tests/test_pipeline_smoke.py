from __future__ import annotations

import shutil
from pathlib import Path

from db.session import SessionLocal, init_db
from pipeline.orchestrator import execute_run


def test_pipeline_smoke_generates_report() -> None:
    import pytest

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe unavailable in environment")

    init_db()
    with SessionLocal() as db:
        result = execute_run(
            db=db,
            scenario_id="urban_dusk",
            options={
                "resize": 640,
                "every_n_frames": 2,
                "max_frames": 30,
                "seed": 1337,
                "disable_stress": False,
            },
        )

    assert result["status"] == "completed"
    assert "readiness" in result
    assert "engagement" in result
    assert "reliability_metrics" in result

    latest_report = Path(result["report_paths"]["latest_report_path"])
    assert latest_report.exists()

    html = latest_report.read_text(encoding="utf-8")
    assert "Counter-UAS Reliability Report" in html
    assert "Readiness" in html
    assert "Reliability Metrics" in html
    assert "Engagement Summary" in html
    assert "Blind Spot Evidence" in html
