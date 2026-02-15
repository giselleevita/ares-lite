from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from db.models import Base, Engagement, Metric, Readiness, Run
from main import _compare_payload


def _make_engine(tmp_path) -> object:
    db_path = tmp_path / "compare.db"
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


def test_compare_payload_structure(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:  # type: ignore[arg-type]
        for rid, precision, readiness in [("run_a", 0.9, 82.0), ("run_b", 0.7, 61.0)]:
            db.add(
                Run(
                    id=rid,
                    scenario_id="urban_dusk",
                    status="completed",
                    stage="completed",
                    progress=100,
                    message="Completed",
                    error_message="",
                    config_json="{}",
                    created_at=now,
                    updated_at=now,
                    queued_at=now,
                    started_at=now,
                    finished_at=now,
                )
            )
            db.add(Metric(run_id=rid, metrics_json=f'{{"precision": {precision}, "recall": 0.8, "baseline_missing": true}}'))
            db.add(Readiness(run_id=rid, readiness_json=f'{{"readiness_score": {readiness}, "recommendation": "READY"}}'))
            db.add(Engagement(run_id=rid, engagement_json='{"engagement_success_rate": 0.5}'))
        db.commit()

        payload = _compare_payload(db, ["run_a", "run_b"], baseline_run_id="run_a")
        assert "runs" in payload
        assert "aligned" in payload
        assert payload.get("baseline_run_id") == "run_a"
        assert len(payload["runs"]) == 2
        assert isinstance(payload["aligned"], list)
        # Ensure readiness is present for both runs.
        run_ids = {item["id"] for item in payload["runs"]}
        assert run_ids == {"run_a", "run_b"}


def test_compare_payload_includes_deltas(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:  # type: ignore[arg-type]
        for rid, precision, readiness in [("run_a", 0.9, 82.0), ("run_b", 0.7, 61.0)]:
            db.add(
                Run(
                    id=rid,
                    scenario_id="urban_dusk",
                    status="completed",
                    stage="completed",
                    progress=100,
                    message="Completed",
                    error_message="",
                    config_json="{}",
                    created_at=now,
                    updated_at=now,
                    queued_at=now,
                    started_at=now,
                    finished_at=now,
                )
            )
            db.add(Metric(run_id=rid, metrics_json=f'{{"precision": {precision}, "recall": 0.8, "baseline_missing": true}}'))
            db.add(Readiness(run_id=rid, readiness_json=f'{{"readiness_score": {readiness}, "recommendation": "READY"}}'))
            db.add(Engagement(run_id=rid, engagement_json='{"engagement_success_rate": 0.5}'))
        db.commit()

        payload = _compare_payload(db, ["run_a", "run_b"], baseline_run_id="run_a")
        aligned = payload["aligned"]
        # At least one row has deltas and baseline id.
        row = next((r for r in aligned if r.get("field") == "readiness.readiness_score"), None)
        assert row is not None
        assert row.get("baseline_run_id") == "run_a"
        deltas = row.get("deltas")
        assert isinstance(deltas, dict)
        assert deltas.get("run_a") == 0.0
        assert isinstance(deltas.get("run_b"), float)
