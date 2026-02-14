from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from benchmarking.suite import create_benchmark_suite, suite_status_snapshot
from db.models import Base, BenchmarkItem, BenchmarkSuite, Run


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


def test_create_benchmark_suite_enqueues_runs(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with SessionLocal() as db:  # type: ignore[arg-type]
        suite_id = create_benchmark_suite(
            db=db,
            name="test",
            scenario_ids=["urban_dusk"],
            stress_profile_ids=["light_noise"],
            seeds=[1, 2],
            base_options={"resize": 320, "every_n_frames": 1, "max_frames": 10},
            include_baselines=True,
            validate_scenarios=False,
        )

        suite = db.query(BenchmarkSuite).filter(BenchmarkSuite.id == suite_id).first()
        assert suite is not None

        items = db.query(BenchmarkItem).filter(BenchmarkItem.suite_id == suite_id).all()
        # 1 scenario x 2 seeds => 2 baselines + 2 stressed (light_noise)
        assert len(items) == 4

        run_ids = [item.run_id for item in items]
        runs = db.query(Run).filter(Run.id.in_(run_ids)).all()
        assert len(runs) == 4
        assert all(r.status == "queued" for r in runs)

        snapshot = suite_status_snapshot(db, suite_id)
        assert snapshot is not None
        assert snapshot["id"] == suite_id
        assert snapshot["counts"]["queued"] == 4
        assert snapshot["progress"] == 0


def test_suite_status_snapshot_completed_derivation(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:  # type: ignore[arg-type]
        suite = BenchmarkSuite(id="suite_x", name="x", created_at=now, updated_at=now, status="queued", config_json="{}")
        db.add(suite)
        db.add(
            Run(
                id="run_a",
                scenario_id="urban_dusk",
                status="completed",
                stage="completed",
                progress=100,
                message="Completed",
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
                suite_id="suite_x",
                run_id="run_a",
                scenario_id="urban_dusk",
                seed=1,
                stress_profile_id="none",
                role="baseline",
                created_at=now,
            )
        )
        db.commit()

        snapshot = suite_status_snapshot(db, "suite_x")
        assert snapshot is not None
        assert snapshot["status"] == "completed"
        assert snapshot["progress"] == 100

