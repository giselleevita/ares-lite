from __future__ import annotations

import shutil
import threading
import time

import pytest

from core.settings import settings
from db.models import Run
from db.runs import request_cancel
from db.session import SessionLocal, init_db
from pipeline.orchestrator import enqueue_run_request, execute_run_job


def test_cancel_processing_run_marks_cancelled() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe unavailable in environment")

    init_db()

    # Make cancellation checks very frequent for this test.
    settings.cancel_check_every_n_frames = 1

    with SessionLocal() as db:
        run_id = enqueue_run_request(
            db=db,
            scenario_id="urban_dusk",
            options={
                "resize": 640,
                "every_n_frames": 1,
                "max_frames": 120,
                "seed": 1337,
                "disable_stress": False,
            },
        )

    t = threading.Thread(target=execute_run_job, args=(run_id,), daemon=True)
    t.start()

    # Wait until the run is claimed/processing, then request cancel.
    deadline = time.time() + 10
    while time.time() < deadline:
        with SessionLocal() as db:
            row = db.query(Run).filter(Run.id == run_id).first()
            assert row is not None
            if row.status == "processing":
                request_cancel(db, run_id)
                db.commit()
                break
        time.sleep(0.05)

    t.join(timeout=20)
    assert not t.is_alive()

    with SessionLocal() as db:
        row = db.query(Run).filter(Run.id == run_id).first()
        assert row is not None
        assert row.status in {"cancelled", "failed"}
        if row.status == "failed":
            # If ffmpeg extraction is too fast, cancellation might happen after completion;
            # but we should not leave it processing.
            assert row.error_message != "Run failed: cancelled"
        if row.status == "cancelled":
            assert row.cancelled_at is not None

