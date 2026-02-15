from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from benchmarking.export import export_batch_csv
from db.models import Base, BenchmarkBatch, BenchmarkItem, Engagement, Metric, Readiness, Run


def _make_engine(tmp_path) -> object:
    db_path = tmp_path / "export.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    def _on_connect(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.close()

    event.listen(engine, "connect", _on_connect)
    Base.metadata.create_all(bind=engine)
    return engine


def test_export_batch_csv_includes_items_and_best_effort_fields(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:  # type: ignore[arg-type]
        batch_id = "batch_export"
        db.add(BenchmarkBatch(id=batch_id, name="Export", created_at=now, updated_at=now, status="processing", message="", config_json="{}", summary_json="{}"))

        run_a = "run_a"
        run_b = "run_b"
        db.add(Run(id=run_a, scenario_id="urban_dusk", status="completed", stage="completed", progress=100, message="", error_message="", config_json="{}", created_at=now, updated_at=now, queued_at=now, started_at=now, finished_at=now))
        db.add(Run(id=run_b, scenario_id="urban_dusk", status="failed", stage="inference", progress=55, message="", error_message="boom", config_json="{}", created_at=now, updated_at=now, queued_at=now, started_at=now))

        db.add(
            BenchmarkItem(
                batch_id=batch_id,
                scenario_id="urban_dusk",
                seed=123,
                stress_profile_json=json.dumps({"id": "fog", "name": "Fog"}),
                run_id=run_a,
                status="completed",
                role="stressed",
                created_at=now,
            )
        )
        db.add(
            BenchmarkItem(
                batch_id=batch_id,
                scenario_id="urban_dusk",
                seed=123,
                stress_profile_json=json.dumps({"id": "baseline", "name": "Baseline"}),
                run_id=run_b,
                status="failed",
                role="baseline",
                created_at=now,
            )
        )

        db.add(Metric(run_id=run_a, metrics_json=json.dumps({"precision": 0.9, "recall": 0.8, "baseline_missing": False})))
        db.add(Readiness(run_id=run_a, readiness_json=json.dumps({"readiness_score": 82.0, "recommendation": "READY"})))
        db.add(Engagement(run_id=run_a, engagement_json=json.dumps({"engagement_success_rate": 0.5})))
        db.commit()

        csv_text = export_batch_csv(db, batch_id)
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        assert len(rows) == 2
        assert reader.fieldnames is not None
        assert "batch_id" in reader.fieldnames
        assert "run_id" in reader.fieldnames
        assert "readiness_score" in reader.fieldnames
        assert "precision" in reader.fieldnames

        by_run = {row["run_id"]: row for row in rows}
        assert by_run[run_a]["stress_profile_id"] == "fog"
        assert by_run[run_a]["readiness_score"] in {"82.0", "82"}
        assert by_run[run_b]["stress_profile_id"] == "baseline"
        assert by_run[run_b]["run_status"] == "failed"
        assert by_run[run_b]["run_error_message"] == "boom"

