from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from benchmarking.batch import create_benchmark_batch, reconcile_batch
from db.models import Base, BenchmarkBatch, BenchmarkItem, Engagement, Metric, Readiness, Run


def _make_engine(tmp_path) -> object:
    db_path = tmp_path / "bench.db"
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


def test_create_benchmark_batch_creates_items_and_runs(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with SessionLocal() as db:  # type: ignore[arg-type]
        batch_id, item_count = create_benchmark_batch(
            db=db,
            name="test",
            scenarios=["urban_dusk"],
            stress_profiles=["baseline", "fog"],
            seeds=[1, 2],
            run_options_overrides={"resize": 320, "every_n_frames": 1, "max_frames": 10},
            validate_scenarios=False,
        )

        assert item_count == 4  # 1 scenario x 2 seeds x 2 profiles
        batch = db.query(BenchmarkBatch).filter(BenchmarkBatch.id == batch_id).first()
        assert batch is not None

        items = db.query(BenchmarkItem).filter(BenchmarkItem.batch_id == batch_id).all()
        assert len(items) == 4
        assert all(item.run_id is not None for item in items)

        run_ids = [item.run_id for item in items if item.run_id]
        runs = db.query(Run).filter(Run.id.in_(run_ids)).all()
        assert len(runs) == 4
        assert all(r.status == "queued" for r in runs)


def test_reconcile_batch_computes_summary_when_terminal(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:  # type: ignore[arg-type]
        batch = BenchmarkBatch(id="batch_x", name="x", created_at=now, updated_at=now, status="queued", message="", config_json="{}", summary_json="{}")
        db.add(batch)

        # Two completed runs under the batch.
        for idx, score in enumerate([80.0, 60.0]):
            run_id = f"run_{idx}"
            db.add(
                Run(
                    id=run_id,
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
            db.add(
                BenchmarkItem(
                    batch_id="batch_x",
                    scenario_id="urban_dusk",
                    seed=idx,
                    stress_profile_json=json.dumps({"id": "fog"}),
                    run_id=run_id,
                    status="completed",
                    role="stressed",
                    created_at=now,
                )
            )
            db.add(Metric(run_id=run_id, metrics_json=json.dumps({"precision": 0.8, "recall": 0.7, "baseline_missing": True})))
            db.add(Readiness(run_id=run_id, readiness_json=json.dumps({"readiness_score": score, "recommendation": "READY" if score >= 75 else "LIMITED"})))
            db.add(Engagement(run_id=run_id, engagement_json=json.dumps({"engagement_success_rate": 0.5})))

        db.commit()

        snapshot = reconcile_batch(db, "batch_x")
        assert snapshot is not None
        assert snapshot["status"] == "completed"
        summary = snapshot["summary"]
        assert isinstance(summary, dict)
        assert "overall" in summary
        assert summary["overall"]["mean_readiness"] is not None
        assert summary["overall"]["worst_readiness"] == 60.0

